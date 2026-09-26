#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""catalogo: administra los autos que muestra el sitio de Mendiautos.

Lo usan el asistente de Telegram (Hermes) y el administrador del servidor.
El catálogo vive fuera del sitio, en /var/lib/mendiautos/catalogo:

  inventario.json   los autos (la fuente de verdad, con historial en git)
  inventario.js     lo que lee el sitio; se genera en cada cambio
  fotos/<id>/       fotos procesadas: <huella>.jpg (1600 px) y <huella>-m.jpg (800 px)

Cada cambio se valida, se escribe de forma atómica y queda en el historial,
así que siempre se puede deshacer. Los datos pertenecen al usuario del
sistema «catalogo»: quien use el comando sin ser root ni ese usuario pasa por
sudo (regla en /etc/sudoers.d/mendiautos-catalogo), y así nadie más puede
escribir en los archivos que publica el sitio.

  catalogo --help          todos los comandos
  catalogo campos          los datos de un auto y los valores aceptados
"""
import argparse
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
import pwd
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time
import unicodedata
import urllib.parse
from pathlib import Path

DUENO = 'catalogo'                        # usuario del sistema dueño de los datos
RUTA_COMANDO = '/usr/local/bin/catalogo'
DATOS = Path(os.environ.get('MENDIAUTOS_CATALOGO') or '/var/lib/mendiautos/catalogo')
CONF_SITIO = Path(os.environ.get('MENDIAUTOS_CONF') or '/etc/mendiautos.conf')
RESPALDOS = Path(os.environ.get('MENDIAUTOS_RESPALDOS') or '/var/backups/mendiautos')
JSON_F = DATOS / 'inventario.json'
JS_F = DATOS / 'inventario.js'
FOTOS = DATOS / 'fotos'
WEB_FOTOS = 'catalogo/fotos'
TZ = dt.timezone(dt.timedelta(hours=-5))  # Colombia no tiene horario de verano

LADO_GRANDE, LADO_MEDIANO, LADO_MINIMO = 1600, 800, 320
MAX_FOTOS = 30                            # por auto
MAX_ARCHIVOS = 30                         # por comando
MAX_BYTES_FOTO = 40 * 1024 * 1024
MAX_BYTES_TOTAL = 200 * 1024 * 1024
EXT_IMAGEN = ('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif')

ESTADOS = ('disponible', 'vendido', 'oculto')  # oculto: en preparación, no sale en el sitio
RE_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,79}$')
RE_FECHA = re.compile(r'^\d{4}-\d{2}-\d{2}$')
RE_FOTO_PROPIA = re.compile(r'^catalogo/fotos/([a-z0-9][a-z0-9-]{0,79})/([0-9a-f]{16})\.jpg$')
RE_FOTO_SITIO = re.compile(r'^assets/[A-Za-z0-9._/-]+\.(?:jpe?g|png|webp)$')


class Fallo(Exception):
    """Error que se le muestra tal cual a quien usa el comando."""


# ------------------------------------------------------------------ textos
def sin_acentos(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s)) if not unicodedata.combining(c))


def clave(s):
    """'Único dueño' -> 'unico_dueno'."""
    return re.sub(r'[^a-z0-9]+', '_', sin_acentos(s).lower()).strip('_')


def slug(*partes):
    s = re.sub(r'[^a-z0-9]+', '-', sin_acentos(' '.join(str(p) for p in partes if p)).lower()).strip('-')
    return s[:60].rstrip('-') or 'auto'


def miles(n):
    return f'{int(n):,}'.replace(',', '.')


def precio_txt(n):
    return '$' + miles(n) if isinstance(n, int) and n > 0 else 'Consultar'


def km_txt(n):
    return miles(n) + ' km' if isinstance(n, int) else 'sin km'


def nombre(a):
    return ' '.join(str(a[k]) for k in ('marca', 'modelo', 'version') if a.get(k))


def titulo(a):
    return ' '.join(x for x in (nombre(a), str(a.get('anio') or '')) if x)


def hoy():
    return dt.datetime.now(TZ).date().isoformat()


def plural(n, uno, varios):
    return f'{n} {uno if n == 1 else varios}'


CONTROL = re.compile('[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]')


def limpiar_texto(v, largo, multilinea=False):
    s = str(v).replace('\r\n', '\n').replace('\r', '\n')
    if multilinea:
        s = s.replace('\\n', '\n')     # «\n» escrito literalmente en la línea de comandos
        s = CONTROL.sub('', s)
        s = '\n'.join(re.sub(r'[ \t]+', ' ', l).strip() for l in s.split('\n'))
        s = re.sub(r'\n{3,}', '\n\n', s).strip()
    else:
        s = re.sub(r'\s+', ' ', CONTROL.sub('', s)).strip()
    if len(s) > largo:
        raise Fallo(f'El texto es demasiado largo ({len(s)} caracteres; máximo {largo}).')
    return s


# --------------------------------------------------------------- vocabularios
# Los filtros de «Autos disponibles» comparan estos valores exactos.
MARCAS = [
    'Alfa Romeo', 'Aston Martin', 'Audi', 'BAIC', 'Bentley', 'BMW', 'BYD', 'Cadillac', 'Changan',
    'Chery', 'Chevrolet', 'Chrysler', 'Citroën', 'Cupra', 'DFSK', 'Dodge', 'DS', 'Ferrari', 'Fiat',
    'Ford', 'Foton', 'Geely', 'GAC', 'Great Wall', 'Haval', 'Hino', 'Honda', 'Hyundai', 'Isuzu',
    'JAC', 'Jaguar', 'Jeep', 'JMC', 'Kia', 'Lamborghini', 'Land Rover', 'Lexus', 'Maserati',
    'Mazda', 'Mercedes-Benz', 'MG', 'Mini', 'Mitsubishi', 'Nissan', 'Opel', 'Peugeot', 'Porsche',
    'RAM', 'Renault', 'Seat', 'Skoda', 'SsangYong', 'Subaru', 'Suzuki', 'Tesla', 'Toyota',
    'Volkswagen', 'Volvo', 'Zotye',
]
MARCAS_ALIAS = {'mercedes': 'Mercedes-Benz', 'benz': 'Mercedes-Benz', 'vw': 'Volkswagen',
                'chevy': 'Chevrolet', 'gm': 'Chevrolet', 'citroen': 'Citroën', 'gwm': 'Great Wall',
                'range_rover': 'Land Rover', 'mini_cooper': 'Mini'}
VOCABULARIOS = {
    'combustible': ({'gasolina': 'Gasolina', 'diesel': 'Diésel', 'acpm': 'Diésel', 'hibrido': 'Híbrido',
                     'hev': 'Híbrido', 'mhev': 'Híbrido', 'hibrido_enchufable': 'Híbrido enchufable',
                     'phev': 'Híbrido enchufable', 'electrico': 'Eléctrico', 'ev': 'Eléctrico',
                     'gas': 'Gas', 'gnv': 'Gas', 'gasolina_y_gas': 'Gasolina y gas'},
                    ['Gasolina', 'Diésel', 'Híbrido', 'Eléctrico']),
    'transmision': ({'automatica': 'Automática', 'automatico': 'Automática', 'at': 'Automática',
                     'cvt': 'Automática', 'dct': 'Automática', 'secuencial': 'Automática',
                     'mecanica': 'Mecánica', 'mecanico': 'Mecánica', 'manual': 'Mecánica', 'mt': 'Mecánica'},
                    ['Automática', 'Mecánica']),
    'carroceria': ({'suv': 'SUV', 'camioneta': 'SUV', 'crossover': 'SUV', 'sedan': 'Sedán',
                    'hatchback': 'Hatchback', 'hatch': 'Hatchback', 'pickup': 'Pickup', 'pick_up': 'Pickup',
                    'platon': 'Pickup', 'coupe': 'Coupé', 'convertible': 'Convertible', 'van': 'Van',
                    'minivan': 'Van', 'station_wagon': 'Station wagon', 'wagon': 'Station wagon'},
                   ['SUV', 'Sedán', 'Hatchback', 'Pickup', 'Coupé']),
    'traccion': ({'4x2': '4x2', '2wd': '4x2', 'fwd': '4x2', 'rwd': '4x2', 'delantera': '4x2',
                  'trasera': '4x2', '4x4': '4x4', '4wd': '4x4', 'awd': 'AWD', 'integral': 'AWD'},
                 ['4x2', '4x4']),
    'condicion': ({'usado': 'Usado', 'usada': 'Usado', 'nuevo': 'Nuevo', 'nueva': 'Nuevo',
                   '0_km': 'Nuevo', '0km': 'Nuevo'}, ['Usado', 'Nuevo']),
    'ciudad': ({'bucaramanga': 'Bucaramanga', 'bogota': 'Bogotá', 'medellin': 'Medellín',
                'cali': 'Cali', 'barranquilla': 'Barranquilla', 'floridablanca': 'Floridablanca',
                'giron': 'Girón', 'piedecuesta': 'Piedecuesta', 'cucuta': 'Cúcuta'},
               ['Bucaramanga', 'Bogotá', 'Medellín', 'Cali', 'Barranquilla']),
}


def leer_vocabulario(campo, v, avisos):
    tabla, filtro = VOCABULARIOS[campo]
    k = clave(v)
    if k in tabla:
        return tabla[k]
    texto = limpiar_texto(v, 40)
    if not texto:
        raise Fallo('está vacío.')
    avisos.append(f'«{texto}» no es un valor de los filtros del sitio para {campo} '
                  f'({", ".join(filtro)}): se guarda igual, pero ese filtro no lo mostrará.')
    return texto


def leer_marca(v, avisos):
    k = clave(v)
    for m in MARCAS:
        if clave(m) == k or clave(m).replace('_', '') == k.replace('_', ''):
            return m
    if k in MARCAS_ALIAS:
        return MARCAS_ALIAS[k]
    texto = limpiar_texto(v, 40)
    if not texto:
        raise Fallo('está vacía.')
    avisos.append(f'La marca «{texto}» no está en la lista conocida; revisa que esté bien escrita.')
    return texto


# ------------------------------------------------------------------ números
def _numero(s):
    """'78.900.000' -> 78900000 · '9,6' -> 9.6 · '1.300' -> 1300."""
    s = s.strip()
    if re.fullmatch(r'\d{1,3}(?:[.,\s]\d{3})+', s):
        return int(re.sub(r'\D', '', s))
    if re.fullmatch(r'\d+(?:[.,]\d+)?', s):
        return float(s.replace(',', '.')) if re.search(r'[.,]', s) else int(s)
    raise ValueError(s)


def leer_precio(v, avisos):
    s = sin_acentos(v).lower()
    s = re.sub(r'\b(cop|pesos|de|colombianos)\b', ' ', s).replace('$', ' ').strip()
    if s in ('', 'consultar', 'a consultar', 'ninguno', 'null', 'none', '0'):
        return None
    m = re.fullmatch(r'([\d.,]+)\s*(millones|millon|mill|mm|m)\.?', s)
    try:
        n = _numero(m.group(1)) * 1_000_000 if m else _numero(s)
    except ValueError:
        raise Fallo(f'«{v}» no es un precio. Escríbelo en pesos: 78900000, 78.900.000 o «78,9 millones».')
    n = int(round(n))
    if not 1_000_000 <= n <= 20_000_000_000:
        raise Fallo(f'{precio_txt(n)} no parece un precio de auto. Escribe el valor completo en pesos, '
                    'por ejemplo 78900000 o «78,9 millones».')
    return n


def leer_km(v, avisos):
    s = re.sub(r'(kilometros|kms|km)\.?', ' ', sin_acentos(v).lower()).strip()
    if s in ('0', 'nuevo', 'cero'):
        return 0
    m = re.fullmatch(r'([\d.,]+)\s*(mil|k)', s)
    try:
        n = int(round(_numero(m.group(1)) * 1000 if m else _numero(s)))
    except ValueError:
        raise Fallo(f'«{v}» no es un kilometraje. Ejemplos: 28400, 28.400 o «28 mil».')
    if not 0 <= n <= 3_000_000:
        raise Fallo(f'{miles(n)} km no parece un kilometraje real.')
    return n


def leer_entero(minimo, maximo, unidad=''):
    def leer(v, avisos):
        if clave(v) in ('ninguno', 'ninguna', 'cero', 'no') and minimo == 0:
            return 0
        m = re.search(r'\d[\d.]*', str(v))
        try:
            n = int(re.sub(r'\D', '', m.group(0))) if m else None
        except ValueError:
            n = None
        if n is None or not minimo <= n <= maximo:
            raise Fallo(f'«{v}» debe ser un número entre {minimo} y {maximo}{unidad}.')
        return n
    return leer


def leer_anio(v, avisos):
    return leer_entero(1950, dt.date.today().year + 1)(v, avisos)


def leer_aceleracion(v, avisos):
    m = re.search(r'\d+(?:[.,]\d+)?', str(v))
    n = float(m.group(0).replace(',', '.')) if m else 0
    if not 1 <= n <= 60:
        raise Fallo(f'«{v}» no es una aceleración 0-100 válida (segundos, por ejemplo 9,6).')
    return round(n, 1)


def leer_cilindraje(v, avisos):
    s = re.sub(r'(cc|cm3|c\.c\.|litros|lts|l)$', '', sin_acentos(v).lower().replace(' ', ''))
    try:
        n = _numero(s)
    except ValueError:
        return limpiar_texto(v, 40)
    cc = int(round(n * 1000)) if n < 10 else int(n)
    if not 50 <= cc <= 10000:
        raise Fallo(f'«{v}» no parece un cilindraje (ejemplos: 1.300 cc, 2.0).')
    return miles(cc) + ' cc'


def leer_placa(v, avisos):
    digitos = re.findall(r'\d', str(v))
    if not digitos:
        raise Fallo('placa_fin es el último dígito de la placa, por ejemplo 3.')
    if len(re.sub(r'\W', '', str(v))) > 1:
        avisos.append('Por privacidad solo se publica el último dígito de la placa.')
    return digitos[-1]


SI = {'si', 's', 'true', 'verdadero', '1', 'yes', 'y', 'x', 'ok', 'claro'}
NO = {'no', 'n', 'false', 'falso', '0', 'ninguno', 'ninguna'}


def leer_si_no(v, avisos):
    k = clave(v)
    if k in SI:
        return True
    if k in NO:
        return False
    raise Fallo(f'«{v}» debe ser sí o no.')


def leer_fecha(v, avisos):
    s = str(v).strip()
    try:
        fecha = dt.date.fromisoformat(s)
    except ValueError:
        raise Fallo(f'«{v}» no es una fecha AAAA-MM-DD (por ejemplo {hoy()}).')
    if fecha.isoformat() > hoy():
        raise Fallo(f'La fecha {s} está en el futuro.')
    return fecha.isoformat()


def texto_de(largo, multilinea=False):
    return lambda v, avisos: limpiar_texto(v, largo, multilinea)


def vocabulario(campo):
    return lambda v, avisos: leer_vocabulario(campo, v, avisos)


# ------------------------------------------------------------------- campos
# (clave, lector, etiqueta, ayuda). El orden es el de «catalogo ver».
CAMPOS = [
    ('marca', leer_marca, 'Marca', 'Renault, Chevrolet, Mercedes-Benz…'),
    ('modelo', texto_de(40), 'Modelo', 'Duster, CX-30…'),
    ('version', texto_de(40), 'Versión', 'Intens, Grand Touring…'),
    ('anio', leer_anio, 'Año', 'año modelo, por ejemplo 2023'),
    ('precio', leer_precio, 'Precio', 'en pesos: 78900000, 78.900.000 o «78,9 millones»; «consultar» lo oculta'),
    ('km', leer_km, 'Kilometraje', '28400, 28.400 o «28 mil»'),
    ('combustible', vocabulario('combustible'), 'Combustible', 'Gasolina, Diésel, Híbrido, Eléctrico'),
    ('transmision', vocabulario('transmision'), 'Transmisión', 'Automática o Mecánica'),
    ('carroceria', vocabulario('carroceria'), 'Carrocería', 'SUV, Sedán, Hatchback, Pickup, Coupé'),
    ('tipo_carroceria', texto_de(40), 'Tipo de carrocería (ficha)', 'Camioneta / SUV'),
    ('traccion', vocabulario('traccion'), 'Tracción', '4x2, 4x4 o AWD'),
    ('motor', texto_de(60), 'Motor', '1.3 Turbo gasolina'),
    ('motor_corto', texto_de(20), 'Motor en corto', '1.3T (si no se da, sale del cilindraje)'),
    ('cilindraje', leer_cilindraje, 'Cilindraje', '1.300 cc, 1300 o 1.3'),
    ('hp', leer_entero(1, 2000, ' HP'), 'Potencia (HP)', '156'),
    ('velocidad_max', leer_entero(1, 500, ' km/h'), 'Velocidad máxima (km/h)', '180'),
    ('aceleracion', leer_aceleracion, 'Aceleración 0-100 (s)', '9,6'),
    ('autonomia', texto_de(40), 'Autonomía', 'para eléctricos: 400 km'),
    ('condicion', vocabulario('condicion'), 'Condición', 'Usado o Nuevo'),
    ('garantia', texto_de(60), 'Garantía', 'Vigente · 2027'),
    ('negociable', leer_si_no, 'Negociable', 'sí / no'),
    ('financiacion', leer_si_no, 'Financiación', 'sí / no'),
    ('permuta', leer_si_no, 'Acepta permuta', 'sí / no'),
    ('unico_dueno', leer_si_no, 'Único dueño', 'sí / no'),
    ('asegurable', leer_si_no, 'Asegurable', 'sí / no'),
    ('blindado', leer_si_no, 'Blindado', 'sí / no'),
    ('color_exterior', texto_de(40), 'Color exterior', 'Gris Cassiopée'),
    ('color_interior', texto_de(40), 'Color interior', 'Negro'),
    ('placa_fin', leer_placa, 'Placa termina en', 'solo el último dígito: 3'),
    ('ciudad', vocabulario('ciudad'), 'Ciudad', 'Bucaramanga (si no se da, se muestra Bucaramanga)'),
    ('referencia', texto_de(20), 'Referencia', 'MND-00123 (se asigna sola al agregar)'),
    ('resumen', texto_de(300), 'Resumen', 'una o dos frases para la ficha'),
    ('descripcion', texto_de(4000, True), 'Descripción', 'párrafos separados por una línea en blanco'),
    ('historial.duenos', leer_entero(0, 30), 'Dueños anteriores', '1'),
    ('historial.siniestros', leer_entero(0, 99), 'Siniestros', '0'),
    ('historial.mantenimientos', leer_entero(0, 999), 'Mantenimientos', '4'),
    ('historial.rtm', texto_de(60), 'Revisión técnico-mecánica', 'Vigente · jun 2027'),
    ('historial.soat', texto_de(60), 'SOAT', 'Vigente · mar 2027'),
    ('historial.prenda', texto_de(60), 'Prenda', 'Sin prenda · a paz y salvo'),
    ('historial.comparendos', texto_de(60), 'Comparendos', 'A paz y salvo'),
    ('destacado', leer_si_no, 'Destacado en la portada', 'sí / no (también: catalogo destacar)'),
    ('vendido_el', leer_fecha, 'Vendido el', 'AAAA-MM-DD (también: catalogo vender)'),
]
LECTORES = {c[0]: c[1] for c in CAMPOS}
ETIQUETAS = {c[0]: c[2] for c in CAMPOS}
ALIAS = {
    'ano': 'anio', 'year': 'anio', 'modelo_ano': 'anio', 'valor': 'precio', 'price': 'precio',
    'kilometraje': 'km', 'kilometros': 'km', 'kms': 'km', 'recorrido': 'km', 'caja': 'transmision',
    'tipo': 'carroceria', 'categoria': 'carroceria', 'cilindrada': 'cilindraje', 'cc': 'cilindraje',
    'potencia': 'hp', 'caballos': 'hp', 'cv': 'hp', 'velocidad': 'velocidad_max',
    'velocidad_maxima': 'velocidad_max', '0_100': 'aceleracion', 'color': 'color_exterior',
    'interior': 'color_interior', 'tapiceria': 'color_interior', 'placa': 'placa_fin',
    'terminacion_placa': 'placa_fin', 'placa_termina': 'placa_fin', 'unico_propietario': 'unico_dueno',
    'duenos': 'historial.duenos', 'propietarios': 'historial.duenos', 'siniestros': 'historial.siniestros',
    'choques': 'historial.siniestros', 'mantenimientos': 'historial.mantenimientos',
    'rtm': 'historial.rtm', 'tecnomecanica': 'historial.rtm', 'revision_tecnomecanica': 'historial.rtm',
    'soat': 'historial.soat', 'prenda': 'historial.prenda', 'comparendos': 'historial.comparendos',
    'multas': 'historial.comparendos', 'financiable': 'financiacion',
    'credito': 'financiacion', 'recibe_permuta': 'permuta', 'acepta_permuta': 'permuta',
    'portada': 'destacado', 'fecha_venta': 'vendido_el',
}
PROTEGIDOS = {
    'id': 'El id no cambia nunca: si el auto es otro, agrégalo como nuevo.',
    'fotos': 'Las fotos se manejan con: catalogo foto agregar|quitar|portada|orden.',
    'historial.linea': 'La línea de tiempo se maneja con: catalogo linea agregar|quitar.',
    'creado': 'La fecha de creación la pone el sistema.',
}
IMPORTANTES = ['precio', 'km', 'combustible', 'transmision', 'carroceria', 'color_exterior', 'resumen']


def nombre_campo(texto):
    k = clave(texto)
    if k.startswith('historial_') and 'historial.' + k[10:] in LECTORES:
        return 'historial.' + k[10:]
    if k == 'historial_linea':
        return 'historial.linea'
    return ALIAS.get(k, k)


def leer_asignaciones(pares):
    """['precio=75 millones', 'color=Rojo'] -> ([('precio', 75000000), ...], avisos). None = borrar."""
    cambios, avisos, vistos = [], [], set()
    for par in pares:
        if '=' not in par:
            raise Fallo(f'«{par}» no tiene la forma campo=valor (por ejemplo precio=78900000).')
        k, v = par.split('=', 1)
        campo = nombre_campo(k)
        if campo in PROTEGIDOS:
            raise Fallo(PROTEGIDOS[campo])
        if campo != 'estado' and campo not in LECTORES:
            raise Fallo(f'No conozco el campo «{k}». Consulta los campos con: catalogo campos')
        if campo in vistos:
            raise Fallo(f'El campo {campo} aparece dos veces.')
        vistos.add(campo)
        v = v.strip()
        if v == '' or clave(v) in ('borrar', 'quitar', 'eliminar'):
            if campo in ('marca', 'modelo', 'anio', 'estado'):
                raise Fallo(f'{campo} no se puede dejar vacío.')
            cambios.append((campo, None))
            continue
        if campo == 'estado':
            k2 = clave(v)
            if k2 not in ESTADOS:
                raise Fallo('estado debe ser «disponible», «vendido» u «oculto».')
            cambios.append((campo, k2))
            continue
        try:
            cambios.append((campo, LECTORES[campo](v, avisos)))
        except Fallo as e:
            raise Fallo(f'{ETIQUETAS[campo]} ({campo}): {e}')
    return cambios, avisos


def valor(a, campo):
    if campo.startswith('historial.'):
        return (a.get('historial') or {}).get(campo[10:])
    return a.get(campo)


def poner(a, campo, v):
    if campo.startswith('historial.'):
        h = a.setdefault('historial', {})
        if v is None:
            h.pop(campo[10:], None)
            if not h:
                a.pop('historial', None)
        else:
            h[campo[10:]] = v
    elif v is None:
        a.pop(campo, None)
    else:
        a[campo] = v


def mostrar_valor(campo, v):
    if v is None:
        return '—'
    if campo == 'precio':
        return precio_txt(v)
    if campo == 'km':
        return km_txt(v)
    if campo == 'aceleracion':
        return f'{v:.1f}'.replace('.', ',') + ' s'
    if v is True:
        return 'sí'
    if v is False:
        return 'no'
    s = re.sub(r'\n+', ' ¶ ', str(v))
    return s if len(s) <= 90 else s[:87] + '…'


# ------------------------------------------------------------------ validación
TIPOS = {'anio': int, 'precio': int, 'km': int, 'hp': int, 'velocidad_max': int,
         'aceleracion': (int, float), 'destacado': bool, 'negociable': bool, 'financiacion': bool,
         'permuta': bool, 'unico_dueno': bool, 'asegurable': bool, 'blindado': bool}
CONOCIDOS = {c for c in LECTORES if '.' not in c} | {'id', 'estado', 'fotos', 'historial', 'creado'}


def problemas_de(a, pos):
    """Lista de problemas de un auto (vacía si está bien)."""
    if not isinstance(a, dict):
        return [f'posición {pos}: no es un auto']
    ref = f'{a.get("id") or "posición " + str(pos)}'
    p = []
    if not isinstance(a.get('id'), str) or not RE_ID.match(a['id']):
        p.append(f'{ref}: id inválido')
    for k in ('marca', 'modelo'):
        if not isinstance(a.get(k), str) or not a[k].strip():
            p.append(f'{ref}: falta {k}')
    if not isinstance(a.get('anio'), int) or isinstance(a.get('anio'), bool):
        p.append(f'{ref}: falta el año')
    if a.get('estado', 'disponible') not in ESTADOS:
        p.append(f'{ref}: estado debe ser disponible, vendido u oculto')
    for k, t in TIPOS.items():
        if k in a and a[k] is not None and (not isinstance(a[k], t) or (t is int and isinstance(a[k], bool))):
            p.append(f'{ref}: {k} tiene un tipo incorrecto')
    for k in ('vendido_el', 'creado'):
        if k in a and not (isinstance(a[k], str) and RE_FECHA.match(a[k])):
            p.append(f'{ref}: {k} debe ser AAAA-MM-DD')
    for k, v in a.items():
        if k not in CONOCIDOS:
            p.append(f'{ref}: campo desconocido «{k}»')
        elif k not in TIPOS and k not in ('fotos', 'historial') and v is not None and not isinstance(v, str):
            p.append(f'{ref}: {k} debe ser texto')
    fotos = a.get('fotos', [])
    if not isinstance(fotos, list):
        p.append(f'{ref}: fotos debe ser una lista')
    else:
        for f in fotos:
            m = RE_FOTO_PROPIA.match(f) if isinstance(f, str) else None
            if not (m and m.group(1) == a.get('id')) and not (
                    isinstance(f, str) and RE_FOTO_SITIO.match(f) and '..' not in f):
                p.append(f'{ref}: foto inválida {f!r}')
        if len(fotos) != len(set(map(str, fotos))):
            p.append(f'{ref}: fotos repetidas')
    h = a.get('historial', {})
    if not isinstance(h, dict):
        p.append(f'{ref}: historial debe ser un objeto')
    else:
        for k, v in h.items():
            if k == 'linea':
                if not isinstance(v, list) or not all(
                        isinstance(x, dict) and isinstance(x.get('titulo', ''), str)
                        and isinstance(x.get('texto', ''), str) for x in v):
                    p.append(f'{ref}: historial.linea mal formada')
            elif 'historial.' + k not in LECTORES:
                p.append(f'{ref}: historial.{k} desconocido')
            elif k in ('duenos', 'siniestros', 'mantenimientos'):
                if not isinstance(v, int) or isinstance(v, bool):
                    p.append(f'{ref}: historial.{k} debe ser un número')
            elif not isinstance(v, str):
                p.append(f'{ref}: historial.{k} debe ser texto')
    return p


def problemas(datos):
    if not isinstance(datos, list):
        return ['el catálogo no es una lista de autos']
    p, ids = [], set()
    for i, a in enumerate(datos, 1):
        p += problemas_de(a, i)
        if isinstance(a, dict) and a.get('id') in ids:
            p.append(f'{a["id"]}: id repetido')
        ids.add(a.get('id') if isinstance(a, dict) else None)
    return p


# ----------------------------------------------------------------- archivos
def escribir_atomico(ruta, contenido, modo=0o644):
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix='.' + ruta.name + '.')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, modo)
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    try:
        dfd = os.open(ruta.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def cargar():
    try:
        texto = JSON_F.read_text('utf-8')
    except FileNotFoundError:
        raise Fallo(f'No existe el catálogo en {DATOS}. El administrador lo crea con: catalogo iniciar')
    try:
        datos = json.loads(texto)
    except ValueError as e:
        raise Fallo(f'inventario.json está dañado ({e}). Recupéralo con: catalogo deshacer')
    if not isinstance(datos, list):
        raise Fallo('inventario.json está dañado: no es una lista de autos.')
    return datos


def js_de(datos):
    cuerpo = json.dumps(datos, ensure_ascii=True, indent=1)
    return ('/* Generado por el comando catalogo el ' + dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M') +
            '. No lo edites a mano. */\nwindow.MND_INVENTARIO = ' + cuerpo + ';\n').encode('ascii')


def datos_de_js(texto):
    """Extrae la lista de un inventario.js (el del sitio o uno generado)."""
    m = re.search(r'window\.MND_INVENTARIO\s*=\s*(\[.*\])\s*;?\s*$', texto, re.S)
    if not m:
        raise Fallo('El archivo no tiene la forma «window.MND_INVENTARIO = [...]».')
    try:
        return json.loads(m.group(1))
    except ValueError as e:
        raise Fallo(f'El inventario no es JSON válido ({e}).')


def guardar(datos, mensaje, nota='', marca=''):
    p = problemas(datos)
    if p:
        raise Fallo('No guardé nada porque el catálogo quedaría con errores:\n  ' + '\n  '.join(p[:20]))
    escribir_atomico(JSON_F, (json.dumps(datos, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    escribir_atomico(JS_F, js_de(datos))
    registrar(mensaje, nota, marca)


def git(*args, check=True):
    env = dict(os.environ, GIT_AUTHOR_NAME='Catálogo Mendiautos', GIT_AUTHOR_EMAIL='catalogo@localhost',
               GIT_COMMITTER_NAME='Catálogo Mendiautos', GIT_COMMITTER_EMAIL='catalogo@localhost',
               GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
               TZ='COT5', LC_ALL='C.UTF-8')
    try:
        r = subprocess.run(['git', '-C', str(DATOS), *args], capture_output=True, text=True, env=env)
    except FileNotFoundError:
        raise Fallo('Falta git en el servidor (apt install git).')
    if check and r.returncode:
        raise Fallo(f'git {args[0]} falló: {(r.stderr or r.stdout).strip()}')
    return r.stdout


def registrar(mensaje, nota='', marca=''):
    """Guarda el cambio en el historial. «marca» es una línea de control (p. ej. «Deshace: <hash>»)."""
    git('add', '--', 'inventario.json')
    if not git('status', '--porcelain', '--', 'inventario.json').strip():
        return
    quien = os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name
    nota = limpiar_texto(nota, 200) if nota else ''
    cuerpo = '\n'.join(x for x in (nota and f'Nota: {nota}', f'Usuario: {quien}', marca) if x)
    git('commit', '-q', '--no-verify', '-m', mensaje, '-m', cuerpo)


class Candado:
    """Un solo cambio a la vez."""

    def __enter__(self):
        self.f = open(DATOS / '.candado', 'a')
        fin = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() > fin:
                    self.f.close()
                    raise Fallo('El catálogo está ocupado con otro cambio; intenta de nuevo en un momento.')
                time.sleep(0.2)

    def __exit__(self, *exc):
        self.f.close()


def leer_conf():
    vals = {}
    try:
        for linea in CONF_SITIO.read_text('utf-8').splitlines():
            m = re.match(r'^([A-Z_]+)=(.*)$', linea.strip())
            if m:
                try:
                    partes = shlex.split(m.group(2))
                except ValueError:
                    partes = []
                vals[m.group(1)] = partes[0] if partes else ''
    except OSError:
        pass
    return vals


def sitio():
    url = os.environ.get('MENDIAUTOS_URL', '')
    if not url:
        conf = leer_conf()
        url = conf.get('SITIO') or ('https://' + conf['DOMINIO'] if conf.get('DOMINIO') else '')
    return url.rstrip('/')


def enlace(a):
    ruta = 'DetalleAuto.dc.html?id=' + urllib.parse.quote(a['id'])
    base = sitio()
    return f'{base}/{ruta}' if base else ruta


# -------------------------------------------------------------------- autos
def texto_busqueda(a):
    return ' ' + clave(' '.join(str(a.get(k) or '') for k in (
        'id', 'marca', 'modelo', 'version', 'anio', 'color_exterior', 'referencia'))).replace('_', ' ') + ' '


def buscar_auto(datos, ref, exacto=False):
    ref = str(ref).strip()
    for i, a in enumerate(datos):
        if a.get('id') == ref:
            return i, a
    if exacto:
        raise Fallo(f'No existe un auto con el id «{ref}». Consulta los ids con: catalogo listar --todos')
    palabras = clave(ref).split('_')
    candidatos = [(i, a) for i, a in enumerate(datos)
                  if palabras and all(p in texto_busqueda(a) for p in palabras)]
    if len(candidatos) == 1:
        return candidatos[0]
    if not candidatos:
        raise Fallo(f'No encontré ningún auto que coincida con «{ref}». Consulta: catalogo listar --todos')
    raise Fallo(f'Varios autos coinciden con «{ref}»; usa el id exacto:\n' +
                '\n'.join('  ' + linea_auto(a) for _, a in candidatos))


def linea_auto(a):
    disponible = a.get('estado', 'disponible') == 'disponible'
    marca = '★' if disponible and a.get('destacado') else ' '
    estado = '' if disponible else ' · OCULTO (no sale en el sitio)' if a.get('estado') == 'oculto' else \
        f' · VENDIDO {a.get("vendido_el") or ""}'.rstrip()
    return (f'{a["id"]:<36} {marca} {titulo(a)} · {precio_txt(a.get("precio"))} · '
            f'{km_txt(a.get("km"))} · {plural(len(a.get("fotos") or []), "foto", "fotos")}{estado}')


def faltantes(a):
    f = [k for k in IMPORTANTES if valor(a, k) in (None, '')]
    if not a.get('fotos'):
        f.insert(0, 'fotos')
    return f


def siguiente_referencia(datos):
    n = max([int(m.group(1)) for a in datos
             for m in [re.match(r'^MND-(\d+)$', str(a.get('referencia', '')))] if m] or [0])
    return f'MND-{n + 1:05d}'


def imprimir_avisos(avisos):
    for x in avisos:
        print(f'Aviso: {x}')


def pie(a):
    if a.get('estado') == 'oculto':
        print(f'Enlace (funcionará cuando se publique): {enlace(a)}')
    else:
        print(f'Enlace: {enlace(a)}')


# ----------------------------------------------------------------- comandos
def cmd_listar(a):
    datos = cargar()
    if a.vendidos:
        lista = [x for x in datos if x.get('estado') == 'vendido']
    elif a.ocultos:
        lista = [x for x in datos if x.get('estado') == 'oculto']
    elif a.todos:
        lista = datos
    else:
        lista = [x for x in datos if x.get('estado', 'disponible') == 'disponible']
    if a.buscar:
        palabras = clave(a.buscar).split('_')
        lista = [x for x in lista if all(p in texto_busqueda(x) for p in palabras)]
    n = len(lista)
    tipo = ('vendido' if n == 1 else 'vendidos') if a.vendidos else ('oculto' if n == 1 else 'ocultos') \
        if a.ocultos else 'en total' if a.todos else ('disponible' if n == 1 else 'disponibles')
    print(f'{plural(n, "auto", "autos")} {tipo}' +
          (f' que coincide{"" if n == 1 else "n"} con «{a.buscar}»' if a.buscar else '') + (':' if lista else '.'))
    for x in lista:
        print('  ' + linea_auto(x))
    ocultos = sum(1 for x in datos if x.get('estado') == 'oculto')
    if ocultos and not (a.todos or a.ocultos):
        print(f'Además hay {plural(ocultos, "auto oculto", "autos ocultos")} en preparación (catalogo listar --ocultos).')
    if not (a.vendidos or a.ocultos or a.buscar):
        dest = [x for x in datos if x.get('destacado') and x.get('estado', 'disponible') == 'disponible']
        print(f'★ = destacado en la portada ({len(dest)}; la portada muestra hasta 12).' if dest else
              'Ninguno está destacado: la portada muestra los primeros 12 disponibles.')


def cmd_ver(a):
    datos = cargar()
    _, auto = buscar_auto(datos, a.id)
    if a.json:
        print(json.dumps(auto, ensure_ascii=False, indent=2))
        return
    disponible = auto.get('estado', 'disponible') == 'disponible'
    print(f'{titulo(auto)}  (id: {auto["id"]})')
    estado = 'disponible' if disponible else 'OCULTO (en preparación, no sale en el sitio)' \
        if auto.get('estado') == 'oculto' else f'VENDIDO el {auto.get("vendido_el") or "—"}'
    print('Estado: ' + estado +
          ' · Destacado en la portada: ' + ('sí' if auto.get('destacado') else 'no') +
          (f' · Agregado el {auto["creado"]}' if auto.get('creado') else ''))
    pie(auto)
    for k, _, etiqueta, _ in CAMPOS:
        if k in ('marca', 'modelo', 'version', 'anio', 'destacado', 'vendido_el'):
            continue
        v = valor(auto, k)
        if v not in (None, ''):
            print(f'  {etiqueta + " (" + k + ")":<46} {mostrar_valor(k, v)}')
    fotos = auto.get('fotos') or []
    print(f'Fotos: {len(fotos)}' + (' (la primera es la portada; detalle con: catalogo foto listar ' +
                                   auto['id'] + ')' if fotos else ''))
    linea = (auto.get('historial') or {}).get('linea') or []
    if linea:
        print('Línea de tiempo:')
        for i, p in enumerate(linea, 1):
            print(f'  {i}. {p.get("titulo", "")} — {p.get("texto", "")}')
    f = faltantes(auto)
    if f:
        print('Le falta: ' + ', '.join(f))


def cmd_campos(a):
    print('Campos de un auto (úsalos como campo=valor en agregar y editar;')
    print('un valor vacío, por ejemplo color_interior=, borra el campo):\n')
    for k, _, etiqueta, ayuda in CAMPOS:
        print(f'  {k:<26} {etiqueta}: {ayuda}')
    print('\nTambién se aceptan nombres comunes: año, kilometraje, caja, color, placa, dueños, soat…')
    print('Se manejan con sus propios comandos: estado (vender / disponible), fotos (foto …),')
    print('línea de tiempo del historial (linea …). El id se genera solo y no cambia.')


def cmd_agregar(a):
    cambios, avisos = leer_asignaciones(a.campos)
    nuevos = dict(cambios)
    for k in ('marca', 'modelo', 'anio'):
        if nuevos.get(k) in (None, ''):
            raise Fallo(f'Para agregar un auto necesito al menos marca, modelo y año (falta {k}). '
                        'Ejemplo: catalogo agregar marca=Mazda modelo=CX-30 anio=2024 precio=118000000 km=6200')
    with Candado():
        datos = cargar()
        auto = {'id': '', 'estado': 'oculto' if a.oculto else 'disponible', 'destacado': False}
        for campo, v in cambios:
            if campo == 'estado':
                auto['estado'] = v
            elif v is not None:
                poner(auto, campo, v)
        if auto['estado'] == 'vendido':
            auto.setdefault('vendido_el', hoy())
        if not a.duplicado:
            for otro in datos:
                if all(otro.get(k) == auto.get(k) for k in ('marca', 'modelo', 'anio')) and \
                        otro.get('km') == auto.get('km') and otro.get('estado', 'disponible') == auto['estado']:
                    raise Fallo(f'Ya existe un auto igual: {linea_auto(otro)}\n'
                                'Si de verdad es otro auto, repite el comando con --duplicado.')
        base = slug(auto['marca'], auto['modelo'], auto.get('version'), auto['anio'])
        ids, n, nuevo_id = {x.get('id') for x in datos}, 2, base
        while nuevo_id in ids:
            nuevo_id, n = f'{base}-{n}', n + 1
        auto['id'] = nuevo_id
        auto.setdefault('referencia', siguiente_referencia(datos))
        auto['creado'] = hoy()
        auto['fotos'] = []
        orden = ['id', 'estado', 'destacado'] + [c[0] for c in CAMPOS if '.' not in c[0]]
        auto = {k: auto[k] for k in sorted(auto, key=lambda k: orden.index(k) if k in orden else 99)}
        datos.insert(0, auto)
        guardar(datos, f'agregar: {titulo(auto)} [{auto["id"]}]', a.nota)
    imprimir_avisos(avisos)
    print(f'Agregado: {titulo(auto)} · {precio_txt(auto.get("precio"))} · {km_txt(auto.get("km"))}')
    print(f'id: {auto["id"]} · referencia: {auto.get("referencia")}')
    if auto['estado'] == 'oculto':
        print(f'Está OCULTO: no sale en el sitio hasta que lo publiques con: catalogo disponible {auto["id"]}')
    elif auto['estado'] == 'vendido':
        print('Quedó directamente en «Autos vendidos».')
    else:
        print('Aparece primero en «Autos disponibles». En la portada: ' +
              ('sí, está destacado.' if auto.get('destacado') else 'no (para mostrarlo: catalogo destacar ' + auto['id'] + ').'))
    pie(auto)
    f = faltantes(auto)
    if f:
        print('Le falta: ' + ', '.join(f))


def cmd_editar(a):
    cambios, avisos = leer_asignaciones(a.campos)
    if not cambios:
        raise Fallo('Indica qué cambiar, por ejemplo: catalogo editar ' + a.id + ' precio=75000000')
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        hechos = []
        for campo, v in cambios:
            if campo == 'estado':
                antes = auto.get('estado', 'disponible')
                if v != antes:
                    auto['estado'] = v
                    if v == 'vendido':
                        auto.setdefault('vendido_el', hoy())
                    else:
                        auto.pop('vendido_el', None)
                    hechos.append(f'estado: {antes} → {v}')
                continue
            antes = valor(auto, campo)
            if antes == v:
                continue
            poner(auto, campo, v)
            hechos.append(f'{campo}: {mostrar_valor(campo, antes)} → {mostrar_valor(campo, v)}')
        if not hechos:
            imprimir_avisos(avisos)
            print(f'Sin cambios: {titulo(auto)} ya tenía esos datos.')
            return
        guardar(datos, f'editar: {titulo(auto)} [{auto["id"]}] · ' + '; '.join(
            h.split(':')[0] for h in hechos), a.nota)
    imprimir_avisos(avisos)
    print(f'Actualizado: {titulo(auto)}')
    for h in hechos:
        print('  ' + h)
    pie(auto)


def cmd_vender(a):
    fecha = leer_fecha(a.fecha, []) if a.fecha else hoy()
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        if auto.get('estado') == 'vendido':
            raise Fallo(f'{titulo(auto)} ya estaba vendido (desde el {auto.get("vendido_el") or "—"}).')
        auto['estado'], auto['vendido_el'] = 'vendido', fecha
        guardar(datos, f'vender: {titulo(auto)} [{auto["id"]}] el {fecha}', a.nota)
    print(f'Vendido: {titulo(auto)} (fecha {fecha}).')
    print('Ya no aparece en la portada ni en «Autos disponibles»; ahora está en «Autos vendidos».')
    pie(auto)


def cmd_disponible(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        antes = auto.get('estado', 'disponible')
        if antes == 'disponible':
            raise Fallo(f'{titulo(auto)} ya está disponible.')
        auto['estado'] = 'disponible'
        auto.pop('vendido_el', None)
        guardar(datos, f'{"publicar" if antes == "oculto" else "disponible"}: {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'{"Publicado" if antes == "oculto" else "Disponible de nuevo"}: {titulo(auto)}. Sale en «Autos disponibles»' +
          (' y en la portada.' if auto.get('destacado') else '.'))
    f = faltantes(auto)
    if f:
        print('Le falta: ' + ', '.join(f))
    pie(auto)


def cmd_ocultar(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        if auto.get('estado') == 'oculto':
            raise Fallo(f'{titulo(auto)} ya está oculto.')
        auto['estado'] = 'oculto'
        auto.pop('vendido_el', None)
        guardar(datos, f'ocultar: {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'Oculto: {titulo(auto)} ya no sale en ninguna página del sitio. '
          f'Para publicarlo de nuevo: catalogo disponible {auto["id"]}')


def cmd_destacar(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        quiere = not a.no
        if bool(auto.get('destacado')) == quiere:
            print(f'Sin cambios: {titulo(auto)} ' + ('ya estaba' if quiere else 'no estaba') + ' destacado.')
            return
        auto['destacado'] = quiere
        guardar(datos, f'{"destacar" if quiere else "quitar destacado"}: {titulo(auto)} [{auto["id"]}]', a.nota)
        dest = [x for x in datos if x.get('destacado') and x.get('estado', 'disponible') == 'disponible']
    if quiere:
        print(f'Destacado en la portada: {titulo(auto)}.')
        if auto.get('estado') == 'vendido':
            print('Aviso: está vendido, así que no saldrá en la portada mientras siga vendido.')
    else:
        print(f'Ya no está destacado: {titulo(auto)}.')
    print(f'Destacados disponibles: {len(dest)}' + (' (la portada muestra solo los primeros 12).' if len(dest) > 12 else '.') +
          ('' if dest else ' Sin destacados, la portada muestra los primeros 12 disponibles.'))


def cmd_mover(a):
    with Candado():
        datos = cargar()
        i, auto = buscar_auto(datos, a.id)
        destino = {'primero': 1, 'arriba': 1, 'ultimo': len(datos), 'abajo': len(datos)}.get(clave(a.posicion))
        if destino is None:
            try:
                destino = int(a.posicion)
            except ValueError:
                raise Fallo('La posición es un número (1 = primero), «primero» o «ultimo».')
        destino = max(1, min(len(datos), destino))
        if destino - 1 == i:
            print(f'Sin cambios: {titulo(auto)} ya está en la posición {destino}.')
            return
        datos.insert(destino - 1, datos.pop(i))
        guardar(datos, f'mover: {titulo(auto)} [{auto["id"]}] a la posición {destino}', a.nota)
    print(f'{titulo(auto)} quedó en la posición {destino} de {len(datos)} (es el orden de «Autos disponibles» y de la portada).')


def cmd_eliminar(a):
    if not a.confirmar:
        raise Fallo('Eliminar borra el auto del sitio. Si el auto se vendió, usa mejor: catalogo vender <id>. '
                    'Para eliminarlo de verdad, repite el comando con --confirmar.')
    with Candado():
        datos = cargar()
        i, auto = buscar_auto(datos, a.id, exacto=True)
        datos.pop(i)
        guardar(datos, f'eliminar: {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'Eliminado: {titulo(auto)}. Si fue un error: catalogo deshacer (las fotos se guardan 30 días).')


# -------------------------------------------------------------------- fotos
def procesar_foto(contenido, nombre_archivo):
    """Valida la imagen y devuelve (grande, mediana, huella, aviso). Quita EXIF y GPS."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise Fallo('Falta Pillow para procesar fotos (apt install python3-pil).')
    Image.MAX_IMAGE_PIXELS = 60_000_000
    if len(contenido) > MAX_BYTES_FOTO:
        raise Fallo(f'{nombre_archivo}: la foto pesa más de {MAX_BYTES_FOTO // 1048576} MB.')
    if contenido[4:8] == b'ftyp' and contenido[8:12] in (b'heic', b'heix', b'hevc', b'heim', b'heis', b'mif1', b'msf1'):
        raise Fallo(f'{nombre_archivo}: es una foto HEIC de iPhone y no se puede procesar. '
                    'Pide que la envíen como foto normal (no como archivo) o en JPG.')
    try:
        with Image.open(io.BytesIO(contenido)) as prueba:
            prueba.verify()
        im = Image.open(io.BytesIO(contenido))
        if im.format not in ('JPEG', 'MPO', 'PNG', 'WEBP', 'GIF', 'BMP', 'TIFF'):
            raise Fallo(f'{nombre_archivo}: formato {im.format} no admitido (usa JPG, PNG o WEBP).')
        if im.format in ('JPEG', 'MPO'):
            im.draft('RGB', (LADO_GRANDE * 2, LADO_GRANDE * 2))  # decodifica reducida: menos memoria
        im.load()
    except Image.DecompressionBombError:
        raise Fallo(f'{nombre_archivo}: la imagen es demasiado grande.')
    except Fallo:
        raise
    except Exception as e:  # Pillow lanza varios tipos según el formato dañado
        raise Fallo(f'{nombre_archivo}: no es una imagen válida ({e.__class__.__name__}).')
    icc = im.info.get('icc_profile')
    try:
        im = ImageOps.exif_transpose(im)  # endereza fotos tomadas de lado
    except Exception:
        pass  # EXIF dañado: se usa la imagen tal cual
    if im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info):
        rgba = im.convert('RGBA')
        fondo = Image.new('RGB', im.size, (255, 255, 255))
        fondo.paste(rgba, mask=rgba.split()[-1])
        im = fondo
    elif im.mode == 'CMYK':
        im, icc = im.convert('RGB'), None
    else:
        im = im.convert('RGB')
    ancho, alto = im.size
    if max(ancho, alto) < LADO_MINIMO:
        raise Fallo(f'{nombre_archivo}: la foto es muy pequeña ({ancho}×{alto} px); mínimo {LADO_MINIMO} px.')
    aviso = (f'{nombre_archivo}: la foto es pequeña ({ancho}×{alto} px) y puede verse borrosa.'
             if max(ancho, alto) < 1000 else '')
    lanczos = getattr(Image, 'Resampling', Image).LANCZOS

    def jpeg(imagen, lado, calidad):
        imagen.thumbnail((lado, lado), lanczos)
        salida = io.BytesIO()
        extra = {'icc_profile': icc} if icc else {}
        # Sin exif=: la foto publicada no lleva metadatos (ni la ubicación GPS del celular).
        imagen.save(salida, 'JPEG', quality=calidad, optimize=True, progressive=True, **extra)
        return salida.getvalue()

    grande = jpeg(im, LADO_GRANDE, 82)
    mediana = jpeg(im, LADO_MEDIANO, 78)
    return grande, mediana, hashlib.sha256(grande).hexdigest()[:16], aviso


def ruta_local(web):
    m = RE_FOTO_PROPIA.match(web)
    return FOTOS / m.group(1) / f'{m.group(2)}.jpg' if m else None


def cmd_foto_agregar(a, entradas):
    procesadas, avisos = [], []
    for nombre_archivo, contenido in entradas:
        grande, mediana, huella, aviso = procesar_foto(contenido, nombre_archivo)
        procesadas.append((grande, mediana, huella))
        if aviso:
            avisos.append(aviso)
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        fotos = list(auto.get('fotos') or [])
        nuevas, repetidas = [], 0
        for grande, mediana, huella in procesadas:
            web = f'{WEB_FOTOS}/{auto["id"]}/{huella}.jpg'
            if web in fotos or web in nuevas:
                repetidas += 1
                continue
            nuevas.append(web)
        if len(fotos) + len(nuevas) > MAX_FOTOS:
            raise Fallo(f'Un auto puede tener hasta {MAX_FOTOS} fotos; {titulo(auto)} ya tiene {len(fotos)}.')
        if nuevas:
            carpeta = FOTOS / auto['id']
            carpeta.mkdir(parents=True, exist_ok=True)
            for grande, mediana, huella in procesadas:
                if f'{WEB_FOTOS}/{auto["id"]}/{huella}.jpg' in nuevas:
                    escribir_atomico(carpeta / f'{huella}-m.jpg', mediana)
                    escribir_atomico(carpeta / f'{huella}.jpg', grande)
            auto['fotos'] = nuevas + fotos if a.portada else fotos + nuevas
            guardar(datos, f'fotos: +{len(nuevas)} a {titulo(auto)} [{auto["id"]}]', a.nota)
    imprimir_avisos(avisos)
    if nuevas:
        print(f'{plural(len(nuevas), "foto agregada", "fotos agregadas")} a {titulo(auto)}; '
              f'ahora tiene {len(auto["fotos"])}. ' +
              ('Las nuevas quedaron de primeras (la primera es la portada).' if a.portada else
               'La portada es la foto 1' + (' (una de las nuevas).' if not fotos else '.')))
    if repetidas:
        print(f'{plural(repetidas, "foto ya estaba", "fotos ya estaban")} en el auto; no se '
              f'{"repitió" if repetidas == 1 else "repitieron"}.')
    pie(auto)


def indices(texto_lista, total):
    res = []
    for t in texto_lista:
        for parte in re.split(r'[,\s]+', str(t).strip()):
            if not parte:
                continue
            try:
                n = int(parte)
            except ValueError:
                raise Fallo(f'«{parte}» no es un número de foto.')
            if not 1 <= n <= total:
                raise Fallo(f'La foto {n} no existe: el auto tiene {plural(total, "foto", "fotos")}.')
            if n in res:
                raise Fallo(f'La foto {n} aparece dos veces.')
            res.append(n)
    return res


def cmd_foto_listar(a):
    datos = cargar()
    _, auto = buscar_auto(datos, a.id)
    fotos = auto.get('fotos') or []
    print(f'{titulo(auto)}: {plural(len(fotos), "foto", "fotos")}' + (' (la 1 es la portada)' if fotos else ''))
    base = sitio()
    for i, f in enumerate(fotos, 1):
        local = ruta_local(f)
        mediana = local.with_name(local.stem + '-m.jpg') if local else None
        print(f'  {i}. {base + "/" + f if base else f}' + (f'\n     archivo: {mediana}' if mediana else ''))


def cmd_foto_quitar(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        fotos = list(auto.get('fotos') or [])
        if not fotos:
            raise Fallo(f'{titulo(auto)} no tiene fotos.')
        quitar = set(range(1, len(fotos) + 1)) if a.todas else set(indices(a.numeros, len(fotos)))
        if not quitar:
            raise Fallo('Indica qué fotos quitar (por número, ver: catalogo foto listar) o usa --todas.')
        auto['fotos'] = [f for i, f in enumerate(fotos, 1) if i not in quitar]
        guardar(datos, f'fotos: -{len(quitar)} de {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'{plural(len(quitar), "foto quitada", "fotos quitadas")} de {titulo(auto)}; '
          f'quedan {len(auto["fotos"])}. Se puede deshacer durante 30 días: catalogo deshacer')


def cmd_foto_portada(a):
    a.numeros = [a.numero]
    return cmd_foto_orden(a)


def cmd_foto_orden(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        fotos = list(auto.get('fotos') or [])
        orden = indices(a.numeros, len(fotos))
        if not orden:
            raise Fallo('Indica el nuevo orden, por ejemplo: catalogo foto orden <id> 3 1 2')
        nuevo = [fotos[n - 1] for n in orden] + [f for i, f in enumerate(fotos, 1) if i not in orden]
        if nuevo == fotos:
            print('Sin cambios: las fotos ya estaban en ese orden.')
            return
        auto['fotos'] = nuevo
        guardar(datos, f'fotos: nuevo orden en {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'Listo: la portada de {titulo(auto)} es ahora la que era la foto {orden[0]}.' if len(orden) == 1 else
          f'Nuevo orden de fotos para {titulo(auto)}: ' + ', '.join(map(str, orden)) + ' y luego el resto.')


# ----------------------------------------------------------- línea de tiempo
def cmd_linea_agregar(a):
    t = limpiar_texto(a.titulo, 80)
    x = limpiar_texto(a.texto, 400)
    if not t:
        raise Fallo('El título del hito no puede estar vacío.')
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        linea = auto.setdefault('historial', {}).setdefault('linea', [])
        linea.append({'titulo': t, 'texto': x})
        guardar(datos, f'linea: +1 hito en {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'Hito agregado a la línea de tiempo de {titulo(auto)} (ahora tiene {len(linea)}).')


def cmd_linea_quitar(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        linea = (auto.get('historial') or {}).get('linea') or []
        quitar = set(indices([a.numero], len(linea))) if linea else set()
        if not quitar:
            raise Fallo(f'{titulo(auto)} no tiene hitos en la línea de tiempo.')
        auto['historial']['linea'] = [p for i, p in enumerate(linea, 1) if i not in quitar]
        if not auto['historial']['linea']:
            auto['historial'].pop('linea')
        guardar(datos, f'linea: -1 hito en {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'Hito {a.numero} quitado de {titulo(auto)}.')


def cmd_resumen(a):
    """Informe corto para el equipo (lo envía el asistente cada semana)."""
    datos = cargar()
    hoy_d = dt.datetime.now(TZ).date()
    desde = hoy_d - dt.timedelta(days=a.dias)

    def fecha(s):
        try:
            return dt.date.fromisoformat(s)
        except (TypeError, ValueError):
            return None

    def lista(autos, extra=lambda x: ''):
        return ''.join(f'\n  · {titulo(x)}{extra(x)}' for x in autos[:10]) + \
            (f'\n  · … y {len(autos) - 10} más' if len(autos) > 10 else '')

    disp = [x for x in datos if x.get('estado', 'disponible') == 'disponible']
    vendidos = [x for x in datos if x.get('estado') == 'vendido' and (fecha(x.get('vendido_el')) or dt.date.min) >= desde]
    nuevos = [x for x in datos if (fecha(x.get('creado')) or dt.date.min) >= desde]
    sin_fotos = [x for x in disp if not x.get('fotos')]
    sin_precio = [x for x in disp if not x.get('precio')]
    quietos = [x for x in disp if fecha(x.get('creado')) and (hoy_d - fecha(x['creado'])).days > 60]
    dest = sum(1 for x in disp if x.get('destacado'))
    ocultos = [x for x in datos if x.get('estado') == 'oculto']
    meses = 'ene feb mar abr may jun jul ago sep oct nov dic'.split()
    corta = lambda d: f'{d.day} {meses[d.month - 1]}'
    print(f'Catálogo Mendiautos · {corta(desde)} al {corta(hoy_d)}')
    print(f'{plural(len(disp), "auto disponible", "autos disponibles")} ({dest} en la portada) · '
          f'{plural(len(vendidos), "vendido", "vendidos")} y {plural(len(nuevos), "nuevo", "nuevos")} en estos {a.dias} días.')
    if vendidos:
        print('Vendidos:' + lista(vendidos, lambda x: f' ({corta(fecha(x["vendido_el"]))})'))
    if nuevos:
        print('Nuevos:' + lista(nuevos))
    if sin_fotos:
        print('Sin fotos (se ven con un recuadro vacío):' + lista(sin_fotos))
    if sin_precio:
        print('Sin precio (muestran «Consultar»):' + lista(sin_precio))
    if quietos:
        print('Publicados hace más de 60 días:' + lista(quietos, lambda x: f' (desde el {corta(fecha(x["creado"]))})'))
    if ocultos:
        print('Ocultos, en preparación:' + lista(ocultos))
    if not (sin_fotos or sin_precio):
        print('Todos los autos disponibles tienen fotos y precio. 👍')


# ----------------------------------------------------------------- historial
def registros(n=200):
    salida = git('log', f'-n{n}', '--format=%H%x1f%ad%x1f%s%x1f%b%x1e', '--date=format-local:%Y-%m-%d %H:%M',
                 '--', 'inventario.json', check=False)
    res = []
    for r in salida.split('\x1e'):
        partes = r.strip('\n').split('\x1f')
        if len(partes) == 4:
            res.append(dict(zip(('hash', 'fecha', 'asunto', 'cuerpo'), partes)))
    return res


def cmd_historial(a):
    regs = registros(max(1, min(a.n, 500)))
    if not regs:
        print('Todavía no hay cambios registrados.')
        return
    print(f'Últimos {len(regs)} cambios (hora de Colombia):')
    for r in regs:
        nota = re.search(r'^Nota: (.*)$', r['cuerpo'], re.M)
        print(f'  {r["hash"][:8]}  {r["fecha"]}  {r["asunto"]}' + (f'  ({nota.group(1)})' if nota else ''))


def version_en(h):
    try:
        return json.loads(git('show', f'{h}:inventario.json'))
    except (Fallo, ValueError):
        return None


def cmd_deshacer(a):
    with Candado():
        deshechos, objetivo = set(), None
        for r in registros(400):
            m = re.search(r'^Deshace: ([0-9a-f]{40})$', r['cuerpo'], re.M)
            if m:
                deshechos.add(m.group(1))
                continue
            if r['hash'] in deshechos:
                continue
            if r['asunto'].startswith('iniciar'):
                break
            objetivo = r
            break
        if not objetivo:
            raise Fallo('No hay cambios para deshacer.')
        despues, antes = version_en(objetivo['hash']), version_en(objetivo['hash'] + '^')
        if despues is None or antes is None:
            raise Fallo('No pude leer ese cambio en el historial.')
        actual = cargar()
        if actual == despues:
            nuevo = antes
        else:
            # Hubo cambios después: solo se revierten los autos que tocó ese cambio.
            por_id = lambda l: {x.get('id'): x for x in l}
            a_antes, a_despues, a_actual = por_id(antes), por_id(despues), por_id(actual)
            tocados = [i for i in set(a_antes) | set(a_despues) if a_antes.get(i) != a_despues.get(i)]
            if not tocados:
                raise Fallo('Ese cambio solo movió el orden y hubo cambios después; no se puede deshacer solo.')
            conflicto = [i for i in tocados if a_actual.get(i) != a_despues.get(i)]
            if conflicto and not a.forzar:
                raise Fallo('No puedo deshacer «' + objetivo['asunto'] + '» porque después hubo otros cambios en: ' +
                            ', '.join(conflicto) + '. Revísalo con catalogo historial; '
                            'para forzarlo (se pierden esos cambios posteriores) usa --forzar.')
            nuevo = list(actual)
            for i in tocados:
                pos = next((n for n, x in enumerate(nuevo) if x.get('id') == i), None)
                if i in a_antes and pos is not None:
                    nuevo[pos] = a_antes[i]
                elif i in a_antes:
                    nuevo.insert(min(len(nuevo), [x.get('id') for x in antes].index(i)), a_antes[i])
                elif pos is not None:
                    nuevo.pop(pos)
        perdidas = []
        for auto in nuevo:
            ok = []
            for f in auto.get('fotos') or []:
                local = ruta_local(f)
                if local is None or local.exists():
                    ok.append(f)
                else:
                    perdidas.append(f)
            if 'fotos' in auto:
                auto['fotos'] = ok
        guardar(nuevo, f'deshacer: {objetivo["asunto"]}', a.nota, f'Deshace: {objetivo["hash"]}')
    print(f'Deshecho: {objetivo["asunto"]} (del {objetivo["fecha"]}).')
    if perdidas:
        print(f'Aviso: {plural(len(perdidas), "foto ya no existía", "fotos ya no existían")} y no se recuperaron.')


# -------------------------------------------------------------- mantenimiento
def revisar():
    """Revisa datos, archivos de fotos e inventario.js (lo regenera si quedó desfasado). True si todo está bien."""
    datos = cargar()
    p = problemas(datos)
    for auto in datos:
        for f in (auto.get('fotos') or []) if isinstance(auto, dict) else []:
            local = ruta_local(f) if isinstance(f, str) else None
            if local and not (local.exists() and local.with_name(local.stem + '-m.jpg').exists()):
                p.append(f'{auto.get("id")}: falta el archivo de la foto {f}')
    try:
        js_ok = datos_de_js(JS_F.read_text('utf-8')) == datos
    except (OSError, Fallo):
        js_ok = False
    if not js_ok and not problemas(datos):
        with Candado():
            escribir_atomico(JS_F, js_de(cargar()))
        print('inventario.js no coincidía con inventario.json y se regeneró.')
    if p:
        print('Problemas encontrados:\n  ' + '\n  '.join(p))
        return False
    cuenta = {e: sum(1 for x in datos if x.get('estado', 'disponible') == e) for e in ESTADOS}
    fotos = sum(len(x.get('fotos') or []) for x in datos)
    print(f'Catálogo en orden: {plural(len(datos), "auto", "autos")} '
          f'({plural(cuenta["disponible"], "disponible", "disponibles")}, '
          f'{plural(cuenta["vendido"], "vendido", "vendidos")}' +
          (f', {plural(cuenta["oculto"], "oculto", "ocultos")}' if cuenta['oculto'] else '') +
          f'), {plural(fotos, "foto", "fotos")}.')
    return True


def cmd_validar(a):
    if not revisar():
        raise SystemExit(1)


def referencias(dias):
    refs = {f for x in cargar() for f in (x.get('fotos') or [])}
    desde = f'--since={dias}.days.ago'
    hashes = git('log', desde, '--format=%H', '--', 'inventario.json', check=False).split()
    previo = git('log', '-n1', f'--until={dias}.days.ago', '--format=%H', '--', 'inventario.json', check=False).split()
    for h in hashes + previo:
        for x in version_en(h) or []:
            if isinstance(x, dict):
                refs.update(f for f in (x.get('fotos') or []) if isinstance(f, str))
    return refs


def cmd_limpiar(a):
    if not FOTOS.is_dir():
        print('No hay fotos.')
        return
    with Candado():
        refs = referencias(a.dias)
        limite = time.time() - a.dias * 86400
        borradas = liberado = 0
        for carpeta in FOTOS.iterdir():
            if not carpeta.is_dir():
                continue
            for f in carpeta.iterdir():
                base = f.name[:-6] + '.jpg' if f.name.endswith('-m.jpg') else f.name
                if f'{WEB_FOTOS}/{carpeta.name}/{base}' in refs or f.stat().st_mtime > limite:
                    continue
                liberado += f.stat().st_size
                f.unlink()
                borradas += 1
            if not any(carpeta.iterdir()):
                carpeta.rmdir()
    print(f'Limpieza: {plural(borradas, "archivo borrado", "archivos borrados")} '
          f'({liberado / 1048576:.1f} MB) de fotos sin usar hace más de {a.dias} días.')


def cmd_respaldar(a):
    destino = Path(a.destino) if a.destino else RESPALDOS
    destino.mkdir(parents=True, exist_ok=True)
    nombre_tar = f'catalogo-{dt.datetime.now(TZ).strftime("%Y%m%d-%H%M%S")}.tar.gz'
    with Candado():
        fd, tmp = tempfile.mkstemp(dir=destino, prefix='.respaldo-')
        try:
            with os.fdopen(fd, 'wb') as f, tarfile.open(fileobj=f, mode='w:gz') as tar:
                tar.add(str(DATOS), arcname='catalogo', filter=lambda t: None if t.name.endswith('/.candado') else t)
            os.chmod(tmp, 0o640)
            os.replace(tmp, destino / nombre_tar)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise
    conservar = max(1, a.conservar)
    for viejo in sorted(destino.glob('catalogo-*.tar.gz'))[:-conservar]:
        viejo.unlink()
    tam = (destino / nombre_tar).stat().st_size / 1048576
    print(f'Respaldo: {destino / nombre_tar} ({tam:.1f} MB). Se conservan los últimos {conservar}.')


def cmd_mantenimiento(a):
    bien = revisar()
    cmd_limpiar(a)
    cmd_respaldar(a)  # se respalda aunque haya problemas: justo entonces sirve tener la copia
    if not bien:
        raise SystemExit(1)


def importar_archivo(ruta):
    texto = Path(ruta).read_text('utf-8')
    try:
        datos = json.loads(texto) if ruta.endswith('.json') else datos_de_js(texto)
    except ValueError as e:
        raise Fallo(f'{ruta} no es JSON válido ({e}).')
    p = problemas(datos)
    if p:
        raise Fallo(f'{ruta} tiene errores:\n  ' + '\n  '.join(p[:20]))
    return datos


def cmd_iniciar(a):
    DATOS.mkdir(parents=True, exist_ok=True)
    FOTOS.mkdir(exist_ok=True)
    if not (DATOS / '.git').exists():
        git('init', '-q')
        (DATOS / '.gitignore').write_text('# Solo se versiona inventario.json\n*\n!inventario.json\n!.gitignore\n')
    if JSON_F.exists():
        if not JS_F.exists():
            escribir_atomico(JS_F, js_de(cargar()))
        print(f'El catálogo ya existe en {DATOS} ({len(cargar())} autos); no se cambió nada.')
        return
    datos = importar_archivo(a.desde) if a.desde else []
    with Candado():
        guardar(datos, f'iniciar: {plural(len(datos), "auto", "autos")}' + (f' desde {a.desde}' if a.desde else ''))
    print(f'Catálogo creado en {DATOS} con {plural(len(datos), "auto", "autos")}.')


def cmd_importar(a):
    if not a.confirmar:
        raise Fallo('Importar reemplaza todo el catálogo. Repite con --confirmar (se puede deshacer).')
    datos = importar_archivo(a.archivo)
    with Candado():
        guardar(datos, f'importar: {plural(len(datos), "auto", "autos")} desde {Path(a.archivo).name}', a.nota)
    print(f'Catálogo reemplazado: {plural(len(datos), "auto", "autos")}. Si fue un error: catalogo deshacer')


# ------------------------------------------------------ entrada de fotos y sudo
def fotos_recientes(n, minutos, carpeta=None):
    """Las n últimas imágenes que recibió Hermes (Telegram las deja en su caché)."""
    home = Path(os.environ.get('HERMES_HOME') or Path.home() / '.hermes')
    dirs = [Path(carpeta)] if carpeta else [home / 'cache' / 'images', home / 'cache' / 'documents',
                                            home / 'image_cache', home / 'document_cache']
    limite = time.time() - minutos * 60
    halladas = []
    for d in dirs:
        if d.is_dir():
            for f in d.iterdir():
                try:
                    st = f.stat()
                except OSError:
                    continue
                if f.is_file() and f.suffix.lower() in EXT_IMAGEN and st.st_mtime >= limite:
                    halladas.append((st.st_mtime, str(f)))
    halladas.sort()
    if len(halladas) < n:
        raise Fallo(f'Solo encontré {plural(len(halladas), "foto recibida", "fotos recibidas")} en los últimos '
                    f'{minutos} minutos y pediste {n}. Pide que envíen las fotos otra vez.')
    return [f for _, f in halladas[-n:]]


def leer_archivos(rutas):
    if not rutas:
        raise Fallo('Indica las fotos (rutas de archivo) o usa --ultimas N.')
    if len(rutas) > MAX_ARCHIVOS:
        raise Fallo(f'Máximo {MAX_ARCHIVOS} fotos por comando.')
    res, total = [], 0
    for r in rutas:
        p = Path(r).expanduser()
        if not p.is_file():
            raise Fallo(f'No encuentro el archivo {r}. Las fotos que llegan por Telegram se borran del '
                        'caché a las 24 horas: si es más viejo, pide que las envíen de nuevo.')
        tam = p.stat().st_size
        if tam > MAX_BYTES_FOTO:
            raise Fallo(f'{p.name}: la foto pesa más de {MAX_BYTES_FOTO // 1048576} MB.')
        total += tam
        if total > MAX_BYTES_TOTAL:
            raise Fallo('Son demasiadas fotos pesadas para un solo comando; envíalas en partes.')
        res.append((p.name, p.read_bytes()))
    return res


def empaquetar(entradas):
    partes = [b'%d\n' % len(entradas)]
    for nombre_archivo, contenido in entradas:
        n = nombre_archivo.encode('utf-8')[:200]
        partes += [b'%d %d\n' % (len(n), len(contenido)), n, contenido]
    return b''.join(partes)


def desempaquetar(flujo):
    def linea():
        s = flujo.readline(64)
        if not s.endswith(b'\n'):
            raise Fallo('Entrada interna inválida.')
        return s
    try:
        cuantos = int(linea())
        if not 0 < cuantos <= MAX_ARCHIVOS:
            raise ValueError
        res, total = [], 0
        for _ in range(cuantos):
            ln, lc = map(int, linea().split())
            total += lc
            if not (0 <= ln <= 200 and 0 < lc <= MAX_BYTES_FOTO and total <= MAX_BYTES_TOTAL):
                raise ValueError
            n = flujo.read(ln).decode('utf-8', 'replace')
            c = flujo.read(lc)
            if len(c) != lc:
                raise ValueError
            res.append((CONTROL.sub('', n) or 'foto', c))
        return res
    except ValueError:
        raise Fallo('Entrada interna inválida.')


def como_dueno(argv_interno, entradas):
    """Ejecuta el resto como el usuario «catalogo» (si existe en este servidor)."""
    try:
        pw = pwd.getpwnam(DUENO)
    except KeyError:
        return  # sin usuario dedicado (pruebas): se trabaja como el usuario actual
    if os.geteuid() == pw.pw_uid:
        return
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
        os.environ.update(HOME=pw.pw_dir, USER=DUENO, LOGNAME=DUENO)
        return
    comando = RUTA_COMANDO if os.path.exists(RUTA_COMANDO) else os.path.abspath(sys.argv[0])
    try:
        permitido = subprocess.run(['sudo', '-n', '-l', '-u', DUENO, comando], capture_output=True).returncode == 0
    except FileNotFoundError:
        raise Fallo('Falta sudo en el servidor.')
    if not permitido:
        raise Fallo(f'El usuario {pwd.getpwuid(os.getuid()).pw_name} no tiene permiso para editar el catálogo. '
                    'El administrador lo habilita con: mendiautos hermes')
    sudo = ['sudo', '-n', '-u', DUENO, '--', comando, *argv_interno]
    sys.stdout.flush()
    if entradas is None:
        r = subprocess.run(sudo, stdin=subprocess.DEVNULL)
    else:
        r = subprocess.run(sudo, input=empaquetar(entradas))
    raise SystemExit(r.returncode)


SOLO_ADMIN = {'iniciar', 'importar', 'respaldar', 'mantenimiento', 'limpiar'}


# ------------------------------------------------------------------- parser
class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f'Error: {message}\nAyuda: catalogo --help\n')


def construir_parser():
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument('--nota', default='', help='texto que queda en el historial (quién lo pidió, por qué)')
    p = Parser(prog='catalogo', description='Administra el catálogo de autos del sitio de Mendiautos.',
               epilog='Donde se pide <auto> sirve el id exacto o palabras que lo identifiquen sin ambigüedad '
                      '(por ejemplo «duster 2023»). Los cambios se publican al instante.')
    sub = p.add_subparsers(dest='comando', metavar='comando', parser_class=Parser)
    sub.required = True

    def nuevo(nombre_cmd, ayuda, func=None):
        s = sub.add_parser(nombre_cmd, help=ayuda, description=ayuda, parents=[comun])
        if func:
            s.set_defaults(func=func)
        return s

    s = nuevo('listar', 'lista los autos (por defecto, los disponibles)', cmd_listar)
    g = s.add_mutually_exclusive_group()
    g.add_argument('--todos', action='store_true', help='disponibles y vendidos')
    g.add_argument('--vendidos', action='store_true', help='solo los vendidos')
    g.add_argument('--ocultos', action='store_true', help='solo los ocultos (en preparación)')
    s.add_argument('--buscar', metavar='TEXTO', help='filtra por marca, modelo, año, color o referencia')

    s = nuevo('ver', 'muestra todos los datos de un auto', cmd_ver)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('--json', action='store_true', help='los datos tal como se guardan')

    nuevo('campos', 'lista los datos que se pueden poner a un auto', cmd_campos)

    s = nuevo('agregar', 'agrega un auto: catalogo agregar marca=Mazda modelo=CX-30 anio=2024 precio=118000000 …',
              cmd_agregar)
    s.add_argument('campos', nargs='+', metavar='campo=valor')
    s.add_argument('--duplicado', action='store_true', help='agregarlo aunque ya exista uno igual')
    s.add_argument('--oculto', action='store_true', help='agregarlo sin publicarlo (para completar datos y fotos)')

    s = nuevo('editar', 'cambia datos: catalogo editar <auto> precio=75000000 km=30100', cmd_editar)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('campos', nargs='+', metavar='campo=valor')

    s = nuevo('vender', 'marca el auto como vendido (pasa a «Autos vendidos»)', cmd_vender)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('--fecha', metavar='AAAA-MM-DD', help='fecha de la venta (por defecto, hoy)')

    s = nuevo('disponible', 'publica un auto oculto o vuelve a poner en venta uno vendido', cmd_disponible)
    s.add_argument('id', metavar='<auto>')

    s = nuevo('ocultar', 'saca un auto del sitio sin borrarlo (para prepararlo o pausarlo)', cmd_ocultar)
    s.add_argument('id', metavar='<auto>')

    s = nuevo('destacar', 'muestra el auto en la portada (--no para quitarlo)', cmd_destacar)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('--no', action='store_true', help='quitarlo de la portada')

    s = nuevo('mover', 'cambia el orden: catalogo mover <auto> primero|ultimo|<posición>', cmd_mover)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('posicion', metavar='posición')

    s = nuevo('eliminar', 'borra un auto del sitio (para ventas usa «vender»)', cmd_eliminar)
    s.add_argument('id', metavar='<id exacto>')
    s.add_argument('--confirmar', action='store_true', help='obligatorio')

    s = nuevo('foto', 'fotos de un auto: agregar, listar, quitar, portada, orden')
    fs = s.add_subparsers(dest='accion', metavar='acción', parser_class=Parser)
    fs.required = True
    f = fs.add_parser('agregar', help='agrega fotos: catalogo foto agregar <auto> archivo.jpg … | --ultimas N',
                      parents=[comun])
    f.set_defaults(func=cmd_foto_agregar, recibe_fotos=True)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('archivos', nargs='*', metavar='archivo')
    f.add_argument('--ultimas', type=int, metavar='N', help='las N últimas fotos que llegaron por Telegram')
    f.add_argument('--minutos', type=int, default=120, help='con --ultimas: antigüedad máxima (por defecto 120)')
    f.add_argument('--carpeta', help='con --ultimas: carpeta donde buscar (por defecto, el caché de Hermes)')
    f.add_argument('--portada', action='store_true', help='poner las nuevas primero (la primera es la portada)')
    f.add_argument('--entrada-interna', action='store_true', help=argparse.SUPPRESS)
    f = fs.add_parser('listar', help='lista las fotos numeradas', parents=[comun])
    f.set_defaults(func=cmd_foto_listar)
    f.add_argument('id', metavar='<auto>')
    f = fs.add_parser('quitar', help='quita fotos por número: catalogo foto quitar <auto> 2 5', parents=[comun])
    f.set_defaults(func=cmd_foto_quitar)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('numeros', nargs='*', metavar='número')
    f.add_argument('--todas', action='store_true')
    f = fs.add_parser('portada', help='usa la foto N como portada', parents=[comun])
    f.set_defaults(func=cmd_foto_portada)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('numero', metavar='número')
    f = fs.add_parser('orden', help='reordena: catalogo foto orden <auto> 3 1 2 (las no nombradas van al final)',
                      parents=[comun])
    f.set_defaults(func=cmd_foto_orden)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('numeros', nargs='+', metavar='número')

    s = nuevo('linea', 'línea de tiempo del historial: agregar, quitar')
    ls = s.add_subparsers(dest='accion', metavar='acción', parser_class=Parser)
    ls.required = True
    f = ls.add_parser('agregar', help='catalogo linea agregar <auto> "2024 · Mantenimiento" "Texto"',
                      parents=[comun])
    f.set_defaults(func=cmd_linea_agregar)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('titulo', metavar='título')
    f.add_argument('texto')
    f = ls.add_parser('quitar', help='catalogo linea quitar <auto> <número>', parents=[comun])
    f.set_defaults(func=cmd_linea_quitar)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('numero', metavar='número')

    s = nuevo('resumen', 'informe corto: vendidos, nuevos, autos sin fotos o sin precio', cmd_resumen)
    s.add_argument('--dias', type=int, default=7, help='periodo en días (por defecto 7)')

    s = nuevo('historial', 'últimos cambios del catálogo', cmd_historial)
    s.add_argument('-n', type=int, default=15, help='cuántos (por defecto 15)')

    s = nuevo('deshacer', 'deshace el último cambio (repetir para ir más atrás)', cmd_deshacer)
    s.add_argument('--forzar', action='store_true', help='aunque haya cambios posteriores en el mismo auto')

    nuevo('validar', 'revisa el catálogo y las fotos', cmd_validar)

    s = nuevo('limpiar', 'borra fotos que nadie usa hace más de N días (administrador)', cmd_limpiar)
    s.add_argument('--dias', type=int, default=30)

    s = nuevo('respaldar', 'guarda una copia comprimida del catálogo (administrador)', cmd_respaldar)
    s.add_argument('--destino', help=f'carpeta (por defecto {RESPALDOS})')
    s.add_argument('--conservar', type=int, default=14, help='cuántas copias guardar (por defecto 14)')

    s = nuevo('mantenimiento', 'validar + limpiar + respaldar; lo corre el servidor cada día', cmd_mantenimiento)
    s.set_defaults(dias=30, destino=None, conservar=14)

    s = nuevo('iniciar', 'crea el catálogo si no existe (administrador)', cmd_iniciar)
    s.add_argument('--desde', metavar='ARCHIVO', help='inventario.js o .json con los autos iniciales')

    s = nuevo('importar', 'reemplaza todo el catálogo con un archivo (administrador)', cmd_importar)
    s.add_argument('archivo')
    s.add_argument('--confirmar', action='store_true', help='obligatorio')
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.umask(0o022)  # el sitio (nginx) tiene que poder leer lo que se escribe
    try:
        sys.stdout.reconfigure(errors='replace')
        sys.stderr.reconfigure(errors='replace')
    except AttributeError:
        pass
    args = construir_parser().parse_args(argv)
    try:
        if args.comando in SOLO_ADMIN and os.geteuid() != 0 and 'SUDO_USER' in os.environ:
            raise Fallo('Este comando es solo para el administrador del servidor.')
        entradas, argv_interno = None, argv
        if getattr(args, 'recibe_fotos', False):
            if args.entrada_interna:
                entradas = desempaquetar(sys.stdin.buffer)
            else:
                rutas = args.archivos
                if args.ultimas:
                    if rutas:
                        raise Fallo('Usa archivos o --ultimas, no ambos.')
                    if not 1 <= args.ultimas <= MAX_ARCHIVOS:
                        raise Fallo(f'--ultimas va de 1 a {MAX_ARCHIVOS}.')
                    rutas = fotos_recientes(args.ultimas, args.minutos, args.carpeta)
                entradas = leer_archivos(rutas)
                argv_interno = ['foto', 'agregar', args.id, '--entrada-interna'] + \
                    (['--portada'] if args.portada else []) + (['--nota', args.nota] if args.nota else [])
        como_dueno(argv_interno, entradas)
        if entradas is not None:
            args.func(args, entradas)
        else:
            args.func(args)
    except Fallo as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1
    except BrokenPipeError:  # la salida se cortó (por ejemplo con | head)
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
    except OSError as e:
        print(f'Error del sistema: {e}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
