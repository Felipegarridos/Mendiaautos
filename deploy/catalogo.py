#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""catalogo: administra los autos que muestra el sitio de Mendiautos.

Lo usan el asistente de Telegram (Hermes) y el administrador del servidor.
El catálogo vive fuera del sitio, en /var/lib/mendiautos/catalogo:

  inventario.json   los autos (la fuente de verdad, con historial en git)
  inventario.js     lo que lee el sitio (solo autos publicados); se genera en cada cambio
  sitio.json        portada del inicio y videos de «Otros servicios» (también con historial)
  sitio.js          lo que lee el sitio de sitio.json
  fotos/<id>/       fotos procesadas: <huella>.jpg (1600 px) y <huella>-m.jpg (800 px)
  medios/           foto o video de la portada: <huella>.jpg / <huella>.mp4
  previas/          vistas previas de borradores: <clave>.js (enlace sin publicar)

Un auto nuevo empieza como borrador: no sale en el sitio hasta que alguien
dice «Publicar» y tiene todos los datos obligatorios y de 5 a 15 fotos. Un
borrador sin cambios en 7 días se borra solo.

Cada cambio se valida, se escribe de forma atómica y queda en el historial,
así que siempre se puede deshacer. Los datos pertenecen al usuario del
sistema «catalogo»: quien use el comando sin ser root ni ese usuario pasa por
sudo (regla en /etc/sudoers.d/mendiautos-catalogo), y así nadie más puede
escribir en los archivos que publica el sitio. Por sudo, cada cambio lleva
--por <ID de Telegram> y se revisa contra el equipo (/etc/mendiautos/equipo.json):
un vendedor solo sube y corrige sus propios autos.

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
import secrets
import shlex
import shutil
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
EQUIPO_F = Path(os.environ.get('MENDIAUTOS_EQUIPO') or '/etc/mendiautos/equipo.json')
VISITAS = Path(os.environ.get('MENDIAUTOS_VISITAS') or '/var/lib/mendiautos/visitas')
JSON_F = DATOS / 'inventario.json'
JS_F = DATOS / 'inventario.js'
SITIO_F = DATOS / 'sitio.json'
SITIO_JS = DATOS / 'sitio.js'
FOTOS = DATOS / 'fotos'
MEDIOS = DATOS / 'medios'
PREVIAS = DATOS / 'previas'
WEB_FOTOS = 'catalogo/fotos'
WEB_MEDIOS = 'catalogo/medios'
TZ = dt.timezone(dt.timedelta(hours=-5))  # Colombia no tiene horario de verano

LADO_GRANDE, LADO_MEDIANO, LADO_MINIMO, LADO_PORTADA = 1600, 800, 320, 1920
MIN_FOTOS, MAX_FOTOS = 5, 15              # por auto: para publicar y como tope
MAX_ARCHIVOS = 30                         # por comando
MAX_BYTES_FOTO = 40 * 1024 * 1024
MAX_BYTES_TOTAL = 200 * 1024 * 1024
MAX_BYTES_VIDEO = 60 * 1024 * 1024        # Telegram entrega hasta 20 MB; a mano, algo más
MAX_SEGUNDOS_VIDEO = 60
EXT_IMAGEN = ('.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif')
DIAS_BORRADOR = 7                         # un borrador sin cambios en 7 días se borra
MAX_DESTACADOS = 5                        # autos destacados en el inicio

# borrador: se está subiendo (no sale en el sitio); oculto: publicado antes y
# pausado (tampoco sale). Solo «disponible» y «vendido» llegan a inventario.js.
ESTADOS = ('disponible', 'vendido', 'oculto', 'borrador')
PUBLICOS = ('disponible', 'vendido')
# Datos internos: se guardan en inventario.json pero no se publican.
INTERNOS = ('creado_por', 'actualizado', 'publicado', 'previa', 'no_aplica')
# Datos que ya no se usan: se descartan al leer el catálogo.
RETIRADOS = {'velocidad_max': 'La velocidad máxima ya no se muestra en el sitio; no hace falta.'}
RE_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,79}$')
RE_FECHA = re.compile(r'^\d{4}-\d{2}-\d{2}$')
RE_FOTO_PROPIA = re.compile(r'^catalogo/fotos/([a-z0-9][a-z0-9-]{0,79})/([0-9a-f]{16})\.jpg$')
RE_FOTO_SITIO = re.compile(r'^assets/[A-Za-z0-9._/-]+\.(?:jpe?g|png|webp)$')
RE_MEDIO = re.compile(r'^catalogo/medios/([0-9a-f]{16})\.(jpg|mp4)$')
RE_PREVIA = re.compile(r'^[A-Za-z0-9_-]{22}$')
RE_ACTOR = re.compile(r'^-?[0-9]{3,20}$')


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


# ------------------------------------------------------------------- videos
# Recorrido de un auto: un reel o publicación de Instagram (o un video de
# YouTube). Se guarda la dirección canónica, sin parámetros de seguimiento.
RE_INSTAGRAM = re.compile(
    r'^(?:https?://)?(?:www\.|m\.)?(?:instagram\.com|instagr\.am)/(?:[A-Za-z0-9_.]{1,30}/)?'
    r'(reels?|p|tv)/([A-Za-z0-9_-]{5,40})/?(?:[?#].*)?$', re.I)
RE_YOUTUBE = (
    re.compile(r'^(?:https?://)?(?:www\.|m\.|music\.)?youtube(?:-nocookie)?\.com/'
               r'(?:watch\?(?:[^#]*&)?v=|embed/|shorts/|live/|v/)([A-Za-z0-9_-]{11})(?:[?&#/].*)?$', re.I),
    re.compile(r'^(?:https?://)?youtu\.be/([A-Za-z0-9_-]{11})(?:[?&#/].*)?$', re.I),
)


def youtube_de(v):
    s = str(v).strip()
    for r in RE_YOUTUBE:
        m = r.match(s)
        if m:
            return f'https://www.youtube.com/watch?v={m.group(1)}'
    return None


def leer_video(v, avisos):
    s = str(v).strip()
    m = RE_INSTAGRAM.match(s)
    if m:
        tipo = 'reel' if m.group(1).lower().startswith('reel') else m.group(1).lower()
        return f'https://www.instagram.com/{tipo}/{m.group(2)}/'
    y = youtube_de(s)
    if y:
        return y
    raise Fallo(f'«{limpiar_texto(s, 200)}» no es un enlace de un reel de Instagram '
                '(https://www.instagram.com/reel/…) ni de un video de YouTube.')


def leer_youtube(v):
    y = youtube_de(v)
    if not y:
        raise Fallo(f'«{limpiar_texto(str(v), 200)}» no es un enlace de YouTube '
                    '(https://www.youtube.com/watch?v=… o https://youtu.be/…).')
    return y


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
    ('aceleracion', leer_aceleracion, 'Aceleración 0-100 (s)', '9,6 (opcional; si no se da, no se muestra)'),
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
    ('video', leer_video, 'Video del recorrido', 'enlace de un reel de Instagram (o de YouTube)'),
    ('historial.duenos', leer_entero(0, 30), 'Dueños anteriores', '1'),
    ('historial.siniestros', leer_entero(0, 99), 'Siniestros', '0'),
    ('historial.mantenimientos', leer_entero(0, 999), 'Mantenimientos', '4'),
    ('historial.rtm', texto_de(60), 'Revisión técnico-mecánica', 'Vigente · jun 2027'),
    ('historial.soat', texto_de(60), 'SOAT', 'Vigente · mar 2027'),
    ('historial.prenda', texto_de(60), 'Prenda', 'Sin prenda · a paz y salvo'),
    ('historial.comparendos', texto_de(60), 'Comparendos', 'A paz y salvo'),
    ('vendido_el', leer_fecha, 'Vendido el', 'AAAA-MM-DD (para corregir la fecha de una venta)'),
]
LECTORES = {c[0]: c[1] for c in CAMPOS}
ETIQUETAS = {c[0]: c[2] for c in CAMPOS}
ALIAS = {
    'ano': 'anio', 'year': 'anio', 'modelo_ano': 'anio', 'valor': 'precio', 'price': 'precio',
    'kilometraje': 'km', 'kilometros': 'km', 'kms': 'km', 'recorrido': 'km', 'caja': 'transmision',
    'tipo': 'carroceria', 'categoria': 'carroceria', 'cilindrada': 'cilindraje', 'cc': 'cilindraje',
    'potencia': 'hp', 'caballos': 'hp', 'cv': 'hp', 'velocidad': 'velocidad_max',
    'velocidad_maxima': 'velocidad_max', '0_100': 'aceleracion', 'color': 'color_exterior',
    'reel': 'video', 'instagram': 'video', 'youtube': 'video', 'video_recorrido': 'video',
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
    'estado': 'El estado se cambia con: catalogo publicar, vender, reactivar u ocultar.',
    'destacado': 'Los destacados del inicio se manejan con: catalogo destacar <auto> [--no].',
    'creado_por': 'Quién subió el auto lo anota el sistema.',
    'actualizado': 'La fecha del último cambio la pone el sistema.',
    'publicado': 'La fecha de publicación la pone el sistema.',
    'previa': 'La vista previa se maneja con: catalogo previa <auto>.',
    'no_aplica': 'Para marcar un dato como «no aplica», escribe campo="no aplica".',
}

# Datos obligatorios para publicar, en el orden en que el asistente los pide.
# Cada entrada se cumple con cualquiera de sus campos (motor o cilindraje).
REQUERIDOS = [
    ('marca',), ('modelo',), ('version',), ('anio',), ('precio',), ('negociable',), ('km',),
    ('transmision',), ('combustible',), ('carroceria',), ('traccion',), ('motor', 'cilindraje'),
    ('color_exterior',), ('color_interior',), ('placa_fin',), ('ciudad',), ('historial.duenos',),
    ('blindado',), ('asegurable',), ('permuta',), ('financiacion',), ('historial.soat',),
    ('historial.rtm',), ('historial.siniestros',), ('historial.prenda',), ('historial.comparendos',),
    ('historial.mantenimientos',), ('hp',), ('descripcion',),
]
# Estos siempre necesitan un valor real; los demás aceptan «no aplica».
SIN_NO_APLICA = {'marca', 'modelo', 'anio', 'km', 'transmision', 'combustible', 'carroceria',
                 'color_exterior', 'ciudad', 'negociable', 'blindado', 'asegurable', 'permuta',
                 'financiacion', 'unico_dueno', 'descripcion', 'video', 'vendido_el', 'referencia'}
NO_APLICA = object()   # valor leído de «no aplica» (o «consultar» en el precio)
TEXTOS_NO_APLICA = {'no_aplica', 'n_a', 'na', 'no_corresponde', 'no_aplica_para_este_auto'}


def nombre_campo(texto):
    k = clave(texto)
    if k.startswith('historial_') and 'historial.' + k[10:] in LECTORES:
        return 'historial.' + k[10:]
    if k == 'historial_linea':
        return 'historial.linea'
    return ALIAS.get(k, k)


def leer_asignaciones(pares):
    """['precio=75 millones', 'color=Rojo'] -> ([('precio', 75000000), ...], avisos).
    None = borrar el dato · NO_APLICA = «no aplica» (en el precio, «consultar»)."""
    cambios, avisos, vistos = [], [], set()
    for par in pares:
        if '=' not in par:
            raise Fallo(f'«{par}» no tiene la forma campo=valor (por ejemplo precio=78900000).')
        k, v = par.split('=', 1)
        campo = nombre_campo(k)
        if campo in RETIRADOS:
            raise Fallo(RETIRADOS[campo])
        if campo in PROTEGIDOS:
            raise Fallo(PROTEGIDOS[campo])
        if campo not in LECTORES:
            raise Fallo(f'No conozco el campo «{k}». Consulta los campos con: catalogo campos')
        if campo in vistos:
            raise Fallo(f'El campo {campo} aparece dos veces.')
        vistos.add(campo)
        v = v.strip()
        if v == '' or clave(v) in ('borrar', 'quitar', 'eliminar'):
            if campo in ('marca', 'modelo', 'anio'):
                raise Fallo(f'{campo} no se puede dejar vacío.')
            cambios.append((campo, None))
            continue
        if clave(v) in TEXTOS_NO_APLICA:
            if campo in SIN_NO_APLICA:
                raise Fallo(f'{ETIQUETAS[campo]} ({campo}) necesita un valor: aquí no sirve «no aplica».')
            cambios.append((campo, NO_APLICA))
            continue
        try:
            leido = LECTORES[campo](v, avisos)
        except Fallo as e:
            raise Fallo(f'{ETIQUETAS[campo]} ({campo}): {e}')
        cambios.append((campo, NO_APLICA if campo == 'precio' and leido is None else leido))
    return cambios, avisos


def valor(a, campo):
    if campo.startswith('historial.'):
        return (a.get('historial') or {}).get(campo[10:])
    return a.get(campo)


def estado_de(a, campo):
    """El valor de un dato, o NO_APLICA si se marcó «no aplica»."""
    return NO_APLICA if campo in (a.get('no_aplica') or []) else valor(a, campo)


def respondido(a, campo):
    return campo in (a.get('no_aplica') or []) or valor(a, campo) not in (None, '')


def poner(a, campo, v):
    na = [c for c in (a.get('no_aplica') or []) if c != campo]
    if v is NO_APLICA:
        na.append(campo)
        v = None
    orden = [c[0] for c in CAMPOS]
    if na:
        a['no_aplica'] = sorted(set(na), key=lambda c: orden.index(c) if c in orden else 99)
    else:
        a.pop('no_aplica', None)
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
    if v is NO_APLICA:
        return 'Consultar' if campo == 'precio' else 'no aplica'
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


def minuscula(t):
    """'Transmisión' -> 'transmisión', pero 'SOAT' sigue igual."""
    return t[0].lower() + t[1:] if len(t) > 1 and t[1].islower() else t


def etiqueta_de(alternativas):
    return ' o '.join(minuscula(ETIQUETAS[c]) if i else ETIQUETAS[c] for i, c in enumerate(alternativas))


def pendientes(a):
    """Datos obligatorios que le faltan al auto, en el orden en que se piden."""
    return [alt for alt in REQUERIDOS if not any(respondido(a, c) for c in alt)]


# ------------------------------------------------------------------ validación
TIPOS = {'anio': int, 'precio': int, 'km': int, 'hp': int,
         'aceleracion': (int, float), 'destacado': bool, 'negociable': bool, 'financiacion': bool,
         'permuta': bool, 'unico_dueno': bool, 'asegurable': bool, 'blindado': bool}
CONOCIDOS = {c for c in LECTORES if '.' not in c} | {
    'id', 'estado', 'fotos', 'historial', 'creado', 'destacado'} | set(INTERNOS)
RE_VIDEO_GUARDADO = re.compile(r'^https://www\.instagram\.com/(?:reel|p|tv)/[A-Za-z0-9_-]{5,40}/$'
                               r'|^https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}$')


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
        p.append(f'{ref}: estado debe ser disponible, vendido, oculto o borrador')
    for k, t in TIPOS.items():
        if k in a and a[k] is not None and (not isinstance(a[k], t) or (t is int and isinstance(a[k], bool))):
            p.append(f'{ref}: {k} tiene un tipo incorrecto')
    for k in ('vendido_el', 'creado', 'actualizado', 'publicado'):
        if k in a and not (isinstance(a[k], str) and RE_FECHA.match(a[k])):
            p.append(f'{ref}: {k} debe ser AAAA-MM-DD')
    if 'video' in a and not (isinstance(a['video'], str) and RE_VIDEO_GUARDADO.match(a['video'])):
        p.append(f'{ref}: video debe ser un enlace de Instagram o YouTube')
    if 'previa' in a and not (isinstance(a['previa'], str) and RE_PREVIA.match(a['previa'])):
        p.append(f'{ref}: previa inválida')
    if 'creado_por' in a and not (isinstance(a['creado_por'], str) and 0 < len(a['creado_por']) <= 40):
        p.append(f'{ref}: creado_por inválido')
    na = a.get('no_aplica', [])
    if not isinstance(na, list) or not all(isinstance(c, str) and c in LECTORES for c in na):
        p.append(f'{ref}: no_aplica debe ser una lista de campos')
    for k, v in a.items():
        if k not in CONOCIDOS:
            p.append(f'{ref}: campo desconocido «{k}»')
        elif k not in TIPOS and k not in ('fotos', 'historial', 'no_aplica') and v is not None and not isinstance(v, str):
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


def normalizar(datos):
    """Descarta datos que ya no se usan (por ejemplo la velocidad máxima)."""
    if isinstance(datos, list):
        for a in datos:
            if isinstance(a, dict):
                for k in RETIRADOS:
                    a.pop(k, None)
    return datos


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
    return normalizar(datos)


def publico(a):
    """Lo que el sitio puede ver de un auto (sin datos internos)."""
    return {k: v for k, v in a.items() if k not in INTERNOS}


def js_de(datos):
    """inventario.js: solo los autos publicados (ni borradores ni ocultos)."""
    visibles = [publico(a) for a in datos if a.get('estado', 'disponible') in PUBLICOS]
    cuerpo = json.dumps(visibles, ensure_ascii=True, indent=1)
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


def js_previa(a):
    cuerpo = json.dumps(publico(a), ensure_ascii=True, indent=1)
    return ('/* Vista previa de un auto sin publicar. Generado por el comando catalogo. */\n'
            'window.MND_PREVIA = ' + cuerpo + ';\n').encode('ascii')


def escribir_previas(datos):
    """Una vista previa por borrador u oculto que la pidió; borra las que sobran."""
    vigentes = {}
    for a in datos:
        if a.get('previa') and a.get('estado') not in PUBLICOS:
            vigentes[a['previa'] + '.js'] = a
    if not vigentes and not PREVIAS.is_dir():
        return
    PREVIAS.mkdir(exist_ok=True)
    for nombre_f, a in vigentes.items():
        escribir_atomico(PREVIAS / nombre_f, js_previa(a))
    for f in PREVIAS.iterdir():
        if f.is_file() and f.name not in vigentes:
            f.unlink()


def guardar(datos, mensaje, nota='', marca=''):
    p = problemas(datos)
    if p:
        raise Fallo('No guardé nada porque el catálogo quedaría con errores:\n  ' + '\n  '.join(p[:20]))
    escribir_atomico(JSON_F, (json.dumps(datos, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    escribir_atomico(JS_F, js_de(datos))
    escribir_previas(datos)
    registrar(mensaje, nota, marca, 'inventario.json')


# ------------------------------------------------------------ sitio.json
# Portada del inicio y videos de «Otros servicios». Lo que falte, el sitio lo
# toma de su propio diseño (el video y los textos originales).
SERVICIOS = {'posventa': 'Acompañamiento posventa', 'transito': 'Trámites de tránsito',
             'fotografia': 'Fotografía del vehículo', 'acompanamiento': 'Acompañamiento de compra'}
SERVICIOS_ALIAS = {'post_venta': 'posventa', 'tramites': 'transito', 'tramites_de_transito': 'transito',
                   'fotos': 'fotografia', 'sesion_de_fotos': 'fotografia',
                   'acompanamiento_de_compra': 'acompanamiento', 'compra': 'acompanamiento'}


def cargar_sitio():
    try:
        texto = SITIO_F.read_text('utf-8')
    except FileNotFoundError:
        return {}
    try:
        s = json.loads(texto)
    except ValueError as e:
        raise Fallo(f'sitio.json está dañado ({e}). Recupéralo con: catalogo deshacer')
    if not isinstance(s, dict):
        raise Fallo('sitio.json está dañado: no es un objeto.')
    return s


def problemas_sitio(s):
    p = []
    if not isinstance(s, dict):
        return ['sitio.json no es un objeto']
    for k in s:
        if k not in ('portada', 'servicios'):
            p.append(f'sitio: dato desconocido «{k}»')
    po = s.get('portada', {})
    if not isinstance(po, dict):
        p.append('portada debe ser un objeto')
    else:
        for k, v in po.items():
            if k in ('titulo', 'texto', 'auto'):
                if not isinstance(v, str) or len(v) > 120:
                    p.append(f'portada.{k} debe ser texto corto')
            elif k == 'medio':
                ok = isinstance(v, dict) and v.get('tipo') in ('foto', 'video') and \
                    isinstance(v.get('ruta'), str) and RE_MEDIO.match(v['ruta']) and \
                    v['ruta'].endswith('.mp4' if v.get('tipo') == 'video' else '.jpg') and \
                    set(v) <= {'tipo', 'ruta', 'poster'} and \
                    (v.get('poster') is None or (isinstance(v['poster'], str) and RE_MEDIO.match(v['poster'])
                                                 and v['poster'].endswith('.jpg')))
                if not ok:
                    p.append('portada.medio inválido')
            else:
                p.append(f'portada: dato desconocido «{k}»')
    sv = s.get('servicios', {})
    if not isinstance(sv, dict) or not all(
            k in SERVICIOS and isinstance(v, str) and RE_VIDEO_GUARDADO.match(v) and 'youtube' in v
            for k, v in sv.items()):
        p.append('servicios debe tener enlaces de YouTube de: ' + ', '.join(SERVICIOS))
    return p


def js_sitio(s):
    cuerpo = json.dumps(s, ensure_ascii=True, indent=1)
    return ('/* Generado por el comando catalogo el ' + dt.datetime.now(TZ).strftime('%Y-%m-%d %H:%M') +
            '. No lo edites a mano. */\nwindow.MND_SITIO = ' + cuerpo + ';\n').encode('ascii')


def guardar_sitio(s, mensaje, nota='', marca=''):
    p = problemas_sitio(s)
    if p:
        raise Fallo('No guardé nada porque la portada quedaría con errores:\n  ' + '\n  '.join(p[:20]))
    escribir_atomico(SITIO_F, (json.dumps(s, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    escribir_atomico(SITIO_JS, js_sitio(s))
    registrar(mensaje, nota, marca, 'sitio.json')


# ------------------------------------------------------------- historial
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


def registrar(mensaje, nota='', marca='', archivo='inventario.json'):
    """Guarda el cambio en el historial. «marca» es una línea de control (p. ej. «Deshace: <hash>»)."""
    git('add', '-f', '--', archivo)
    if not git('status', '--porcelain', '--', archivo).strip():
        return
    quien = os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name
    nota = limpiar_texto(nota, 200) if nota else ''
    por = f'Por: {ACTOR["id"]}' + (f' ({ACTOR["nombre"]})' if ACTOR['nombre'] else '') if ACTOR['id'] else ''
    cuerpo = '\n'.join(x for x in (nota and f'Nota: {nota}', f'Usuario: {quien}', por, marca) if x)
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


def enlace_previa(a):
    ruta = 'DetalleAuto.dc.html?previa=' + a['previa']
    base = sitio()
    return f'{base}/{ruta}' if base else ruta


# --------------------------------------------------------- equipo y permisos
# El asistente pasa --por <ID de Telegram> de quien le escribe; el rol sale del
# equipo que registra el administrador (mendiautos equipo …). Sin --por, quien
# usa el comando es el administrador del servidor.
ROLES = ('administrador', 'gerente', 'vendedor')
ACTOR = {'id': '', 'nombre': '', 'rol': ''}
POR_SUDO = [False]        # lo llamó otro usuario del sistema a través de sudo


def equipo():
    try:
        datos = json.loads(EQUIPO_F.read_text('utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise Fallo(f'No pude leer el equipo en {EQUIPO_F} ({e}).')
    res = {}
    for m in (datos.get('miembros') if isinstance(datos, dict) else None) or []:
        if isinstance(m, dict) and RE_ACTOR.match(str(m.get('id', ''))) and m.get('rol') in ROLES:
            res[str(m['id'])] = {'id': str(m['id']), 'rol': m['rol'],
                                 'nombre': limpiar_texto(m.get('nombre') or '', 40)}
    return res


def identificar(por):
    if not por:
        return
    if not RE_ACTOR.match(por):
        raise Fallo('--por es el ID numérico de Telegram de quien pide el cambio.')
    m = equipo().get(por)
    if not m:
        raise Fallo('Quien escribe no está registrado en el equipo, así que no puede usar el catálogo. '
                    'El administrador lo agrega con: mendiautos equipo agregar <ID> <nombre> <rol>')
    ACTOR.update(m)


def quien_nombre(ident):
    m = equipo().get(str(ident or ''))
    return m['nombre'] if m and m['nombre'] else ('el administrador' if ident == 'servidor' else 'otra persona')


# Un vendedor sube autos y corrige los que subió; el gerente y el
# administrador pueden todo lo que hace el asistente.
VENDEDOR_PUEDE = {'listar', 'ver', 'campos', 'faltan', 'agregar', 'editar', 'foto', 'foto-listar', 'linea',
                  'previa', 'publicar', 'deshacer', 'borradores', 'destacados', 'validar', 'portada-ver',
                  'servicios-ver', 'eliminar-borrador'}
PROPIOS = {'editar', 'foto', 'linea', 'previa', 'publicar', 'eliminar-borrador'}
LECTURA = {'listar', 'ver', 'campos', 'faltan', 'validar', 'resumen', 'informe', 'borradores',
           'destacados', 'precios', 'historial', 'portada-ver', 'servicios-ver', 'foto-listar'}
NO_PUEDE = {
    'vender': 'Marcar un auto como vendido lo hacen el gerente o el administrador.',
    'reactivar': 'Volver a poner en venta un auto vendido lo hacen el gerente o el administrador.',
    'destacar': 'Los destacados del inicio los eligen el gerente o el administrador.',
    'portada': 'La portada del inicio la cambian el gerente o el administrador.',
    'servicios': 'Los videos de «Otros servicios» los cambian el gerente o el administrador.',
    'resumen': 'Los informes los reciben el gerente y el administrador.',
    'informe': 'Los informes los reciben el gerente y el administrador.',
    'historial': 'El historial de cambios lo ven el gerente y el administrador.',
    'precios': 'El historial de precios lo ven el gerente y el administrador.',
    'eliminar': 'Borrar autos publicados lo hacen el gerente o el administrador.',
}


def exigir(accion, auto=None):
    """Revisa que quien pide (--por) pueda hacer esto con este auto."""
    if not ACTOR['id']:
        if POR_SUDO[0] and accion not in LECTURA:
            raise Fallo('Cada cambio debe decir quién lo pide: --por <ID de Telegram>.')
        return
    if ACTOR['rol'] in ('administrador', 'gerente'):
        return
    if accion not in VENDEDOR_PUEDE:
        raise Fallo(NO_PUEDE.get(accion, 'Eso lo hacen el gerente o el administrador.'))
    if auto is not None and (accion in PROPIOS or auto.get('estado') == 'borrador') \
            and auto.get('creado_por') != ACTOR['id']:
        raise Fallo(f'{titulo(auto)} lo subió {quien_nombre(auto.get("creado_por"))}: '
                    'solo puedes ver y corregir los borradores y autos que tú subiste.')


def de_otro_borrador(a):
    """Borradores ajenos: un vendedor no los ve en los listados."""
    return ACTOR['rol'] == 'vendedor' and a.get('estado') == 'borrador' and a.get('creado_por') != ACTOR['id']


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
    candidatos = [(i, a) for i, a in enumerate(datos) if not de_otro_borrador(a)
                  and palabras and all(p in texto_busqueda(a) for p in palabras)]
    if len(candidatos) == 1:
        return candidatos[0]
    if not candidatos:
        raise Fallo(f'No encontré ningún auto que coincida con «{ref}». Consulta: catalogo listar --todos')
    raise Fallo(f'Varios autos coinciden con «{ref}»; usa el id exacto:\n' +
                '\n'.join('  ' + linea_auto(a) for _, a in candidatos))


def fecha_de(s):
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def hoy_d():
    return dt.datetime.now(TZ).date()


def dias_sin_cambios(a):
    f = fecha_de(a.get('actualizado')) or fecha_de(a.get('creado'))
    return (hoy_d() - f).days if f else 0


def faltantes(a, maximo=6):
    """Lo que le falta para estar completo, en palabras (listados e informes)."""
    n = len(a.get('fotos') or [])
    f = ['fotos' if not n else f'fotos ({n} de {MIN_FOTOS})'] if n < MIN_FOTOS else []
    f += [minuscula(etiqueta_de(alt)) for alt in pendientes(a)]
    return f[:maximo] + ([f'y {len(f) - maximo} más'] if len(f) > maximo else [])


def linea_auto(a):
    estado = a.get('estado', 'disponible')
    marca = '★' if estado == 'disponible' and a.get('destacado') else ' '
    if estado == 'disponible':
        extra = ''
    elif estado == 'vendido':
        extra = f' · VENDIDO {a.get("vendido_el") or ""}'.rstrip()
    elif estado == 'borrador':
        extra = ' · BORRADOR' + (f' (falta: {", ".join(faltantes(a, 3))})' if faltantes(a) else ' (listo para publicar)')
    else:
        extra = ' · OCULTO (no sale en el sitio)'
    return (f'{a["id"]:<36} {marca} {titulo(a)} · {precio_txt(a.get("precio"))} · '
            f'{km_txt(a.get("km"))} · {plural(len(a.get("fotos") or []), "foto", "fotos")}{extra}')


def siguiente_referencia(datos):
    n = max([int(m.group(1)) for a in datos
             for m in [re.match(r'^MND-(\d+)$', str(a.get('referencia', '')))] if m] or [0])
    return f'MND-{n + 1:05d}'


def imprimir_avisos(avisos):
    for x in avisos:
        print(f'Aviso: {x}')


def pie(a):
    if a.get('estado', 'disponible') in PUBLICOS:
        print(f'Enlace: {enlace(a)}')
    elif a.get('previa'):
        print(f'Vista previa (sin publicar): {enlace_previa(a)}')
    else:
        print(f'No sale en el sitio. Vista previa: catalogo previa {a["id"]}')


def tocar(a):
    a['actualizado'] = hoy()


def destacados_de(datos):
    return [x for x in datos if x.get('destacado') and x.get('estado', 'disponible') == 'disponible']


def resumen_pendiente(a):
    """Una línea: lo que le falta a un borrador para publicarse."""
    falta, n = pendientes(a), len(a.get('fotos') or [])
    partes = []
    if falta:
        partes.append(f'{plural(len(falta), "dato", "datos")} (el siguiente: {minuscula(etiqueta_de(falta[0]))})')
    if n < MIN_FOTOS:
        partes.append(f'{MIN_FOTOS - n} {"foto" if MIN_FOTOS - n == 1 else "fotos"} (tiene {n}; mínimo {MIN_FOTOS})')
    return ('Para publicar faltan: ' + ' y '.join(partes) + '. Detalle: catalogo faltan ' + a['id']) if partes \
        else 'Tiene todo lo necesario: se publica cuando digan «Publicar» (catalogo publicar ' + a['id'] + ').'


# ----------------------------------------------------------------- comandos
def cmd_listar(a):
    exigir('listar')
    datos = [x for x in cargar() if not de_otro_borrador(x)]
    if a.vendidos:
        lista, tipo = [x for x in datos if x.get('estado') == 'vendido'], ('vendido', 'vendidos')
    elif a.ocultos:
        lista, tipo = [x for x in datos if x.get('estado') == 'oculto'], ('oculto', 'ocultos')
    elif a.borradores:
        lista, tipo = [x for x in datos if x.get('estado') == 'borrador'], ('borrador', 'borradores')
    elif a.todos:
        lista, tipo = datos, ('en total', 'en total')
    else:
        lista = [x for x in datos if x.get('estado', 'disponible') == 'disponible']
        tipo = ('disponible', 'disponibles')
    if a.buscar:
        palabras = clave(a.buscar).split('_')
        lista = [x for x in lista if all(p in texto_busqueda(x) for p in palabras)]
    n = len(lista)
    encabezado = f'Borradores sin publicar: {n}' if tipo[0] == 'borrador' else \
        f'{plural(n, "auto", "autos")} {tipo[0] if n == 1 else tipo[1]}'
    print(encabezado + (f' que coincide{"" if n == 1 else "n"} con «{a.buscar}»' if a.buscar else '') +
          (':' if lista else '.'))
    for x in lista:
        print('  ' + linea_auto(x))
    if not (a.todos or a.ocultos or a.borradores or a.vendidos):
        for est, nom in (('borrador', 'borrador sin publicar|borradores sin publicar|--borradores'),
                         ('oculto', 'auto oculto|autos ocultos|--ocultos')):
            k = sum(1 for x in datos if x.get('estado') == est)
            uno, varios, opcion = nom.split('|')
            if k:
                print(f'Además hay {plural(k, uno, varios)} (catalogo listar {opcion}).')
    if not (a.vendidos or a.ocultos or a.borradores or a.buscar):
        dest = destacados_de(datos)
        print((f'★ = destacado en el inicio ({len(dest)} de {MAX_DESTACADOS}).' if len(dest) <= MAX_DESTACADOS else
               f'★ = destacado: hay {len(dest)} y el inicio muestra los primeros {MAX_DESTACADOS}.') if dest else
              f'Ninguno está destacado: el inicio muestra los últimos {MAX_DESTACADOS} publicados.')


def cmd_ver(a):
    datos = cargar()
    _, auto = buscar_auto(datos, a.id)
    exigir('ver', auto)
    if a.json:
        print(json.dumps(auto, ensure_ascii=False, indent=2))
        return
    estado = auto.get('estado', 'disponible')
    print(f'{titulo(auto)}  (id: {auto["id"]})')
    texto_estado = {'disponible': 'disponible', 'oculto': 'OCULTO (pausado, no sale en el sitio)',
                    'borrador': 'BORRADOR (sin publicar)'}.get(estado) or f'VENDIDO el {auto.get("vendido_el") or "—"}'
    print('Estado: ' + texto_estado +
          (' · Destacado en el inicio' if estado == 'disponible' and auto.get('destacado') else '') +
          (f' · Subido el {auto["creado"]}' if auto.get('creado') else '') +
          (f' por {quien_nombre(auto["creado_por"])}' if auto.get('creado_por') and ACTOR['rol'] != 'vendedor' else ''))
    pie(auto)
    for k, _, etiqueta, _ in CAMPOS:
        if k in ('marca', 'modelo', 'version', 'anio', 'vendido_el'):
            continue
        v = estado_de(auto, k)
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
    if estado == 'borrador':
        print(resumen_pendiente(auto))
    else:
        f = faltantes(auto)
        if f:
            print('Le falta: ' + ', '.join(f))


def cmd_campos(a):
    print('Campos de un auto (úsalos como campo=valor en agregar y editar;')
    print('un valor vacío, por ejemplo color_interior=, borra el campo):\n')
    for k, _, etiqueta, ayuda in CAMPOS:
        print(f'  {k:<26} {etiqueta}: {ayuda}')
    print('\nPara publicar hacen falta, en este orden: ' +
          ', '.join(minuscula(etiqueta_de(alt)) for alt in REQUERIDOS) +
          f'; y de {MIN_FOTOS} a {MAX_FOTOS} fotos.')
    print('Donde el dato no corresponde se acepta campo="no aplica" (no en marca, modelo, año, kilometraje,')
    print('transmisión, combustible, carrocería, color exterior, ciudad ni en los sí/no). precio=consultar')
    print('oculta el precio. También se aceptan nombres comunes: año, kilometraje, caja, color, placa, soat…')
    print('Se manejan con sus propios comandos: el estado (publicar, vender, reactivar, ocultar), los')
    print('destacados (destacar), las fotos (foto …) y la línea de tiempo (linea …). El id no cambia.')


def cmd_faltan(a):
    datos = cargar()
    _, auto = buscar_auto(datos, a.id)
    exigir('faltan', auto)
    estado = auto.get('estado', 'disponible')
    print(f'{titulo(auto)} (id: {auto["id"]}) · ' + {'borrador': 'BORRADOR sin publicar',
                                                     'oculto': 'OCULTO'}.get(estado, estado))
    falta = pendientes(auto)
    ayudas = {c[0]: c[3] for c in CAMPOS}
    if falta:
        print(f'Faltan {plural(len(falta), "dato", "datos")}; pídelos en este orden:')
        for i, alt in enumerate(falta, 1):
            na = '' if any(c in SIN_NO_APLICA for c in alt) else ' · acepta «no aplica»'
            print(f'  {i}. {etiqueta_de(alt)} ({"/".join(alt)}): {ayudas[alt[0]]}{na}')
    else:
        print('Datos: completos.')
    n = len(auto.get('fotos') or [])
    print(f'Fotos: {n}' + (f' (faltan {MIN_FOTOS - n}; mínimo {MIN_FOTOS})' if n < MIN_FOTOS else
                          f' (bien; máximo {MAX_FOTOS})'))
    print('Video del recorrido (opcional): ' + (auto['video'] if auto.get('video') else 'sin enlace'))
    if estado == 'borrador':
        print('Listo para publicar: ' + ('sí, cuando digan «Publicar».' if not falta and n >= MIN_FOTOS else 'todavía no.'))
    pie(auto)


def cmd_agregar(a):
    exigir('agregar')
    cambios, avisos = leer_asignaciones(a.campos)
    nuevos = dict(cambios)
    for k in ('marca', 'modelo', 'anio'):
        if nuevos.get(k) in (None, '', NO_APLICA):
            raise Fallo(f'Para empezar un auto necesito al menos marca, modelo y año (falta {k}). '
                        'Ejemplo: catalogo agregar marca=Mazda modelo=CX-30 anio=2024')
    with Candado():
        datos = cargar()
        auto = {'id': '', 'estado': 'borrador', 'destacado': False}
        for campo, v in cambios:
            if v is not None:
                poner(auto, campo, v)
        if not a.duplicado:
            for otro in datos:
                if otro.get('estado') != 'vendido' and all(otro.get(k) == auto.get(k) for k in ('marca', 'modelo', 'anio')) \
                        and (otro.get('km') == auto.get('km') or None in (otro.get('km'), auto.get('km'))):
                    raise Fallo(f'Ya existe un auto parecido: {linea_auto(otro)}\n'
                                'Si es el mismo, sigue con ese. Si de verdad es otro auto, repite con --duplicado.')
        base = slug(auto['marca'], auto['modelo'], auto.get('version'), auto['anio'])
        ids, n, nuevo_id = {x.get('id') for x in datos}, 2, base
        while nuevo_id in ids:
            nuevo_id, n = f'{base}-{n}', n + 1
        auto['id'] = nuevo_id
        auto.setdefault('referencia', siguiente_referencia(datos))
        auto['creado'] = auto['actualizado'] = hoy()
        auto['creado_por'] = ACTOR['id'] or 'servidor'
        auto['previa'] = secrets.token_urlsafe(16)
        auto['fotos'] = []
        orden = ['id', 'estado', 'destacado'] + [c[0] for c in CAMPOS if '.' not in c[0]]
        auto = {k: auto[k] for k in sorted(auto, key=lambda k: orden.index(k) if k in orden else 99)}
        datos.insert(0, auto)
        guardar(datos, f'agregar: {titulo(auto)} [{auto["id"]}]', a.nota)
    imprimir_avisos(avisos)
    print(f'Borrador creado: {titulo(auto)} · id: {auto["id"]} · referencia: {auto.get("referencia")}')
    print('No sale en el sitio hasta que digan «Publicar».')
    print(resumen_pendiente(auto))
    pie(auto)


def cmd_editar(a):
    cambios, avisos = leer_asignaciones(a.campos)
    if not cambios:
        raise Fallo('Indica qué cambiar, por ejemplo: catalogo editar ' + a.id + ' precio=75000000')
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        exigir('editar', auto)
        if any(c == 'vendido_el' for c, _ in cambios):
            exigir('vender', auto)
            if auto.get('estado') != 'vendido':
                raise Fallo('La fecha de venta solo se cambia en un auto vendido.')
        hechos, campos = [], []
        for campo, v in cambios:
            antes = estado_de(auto, campo)
            if antes == v:
                continue
            poner(auto, campo, v)
            campos.append(campo)
            hechos.append(f'{ETIQUETAS[campo]}: {mostrar_valor(campo, antes)} → {mostrar_valor(campo, v)}')
        if not hechos:
            imprimir_avisos(avisos)
            print(f'Sin cambios: {titulo(auto)} ya tenía esos datos.')
            return
        tocar(auto)
        guardar(datos, f'editar: {titulo(auto)} [{auto["id"]}] · ' + '; '.join(campos), a.nota)
    imprimir_avisos(avisos)
    print(f'Actualizado: {titulo(auto)}')
    for h in hechos:
        print('  ' + h)
    if auto.get('estado') == 'borrador':
        print(resumen_pendiente(auto))
    pie(auto)


def cmd_publicar(a):
    with Candado():
        datos = cargar()
        i, auto = buscar_auto(datos, a.id)
        exigir('publicar', auto)
        antes = auto.get('estado', 'disponible')
        if antes == 'disponible':
            raise Fallo(f'{titulo(auto)} ya está publicado: {enlace(auto)}')
        if antes == 'vendido':
            raise Fallo(f'{titulo(auto)} está vendido. Para ponerlo de nuevo en venta: '
                        f'catalogo reactivar {auto["id"]} km=<kilometraje actual> precio=<precio>')
        if antes == 'borrador':
            falta, n = pendientes(auto), len(auto.get('fotos') or [])
            motivos = []
            if falta:
                motivos.append('faltan ' + ', '.join(minuscula(etiqueta_de(x)) for x in falta))
            if n < MIN_FOTOS:
                motivos.append(f'tiene {plural(n, "foto", "fotos")} y se necesitan al menos {MIN_FOTOS}')
            if motivos:
                raise Fallo(f'Todavía no se puede publicar {titulo(auto)}: ' + '; '.join(motivos) +
                            f'. Detalle: catalogo faltan {auto["id"]}')
            auto['publicado'] = hoy()
            datos.insert(0, datos.pop(i))      # sale primero en «Autos disponibles»
        auto['estado'] = 'disponible'
        auto.pop('previa', None)
        tocar(auto)
        guardar(datos, f'{"publicar" if antes == "borrador" else "mostrar"}: {titulo(auto)} [{auto["id"]}]', a.nota)
        dest = destacados_de(datos)
    print(f'{"Publicado" if antes == "borrador" else "De nuevo en el sitio"}: {titulo(auto)} · '
          f'{precio_txt(auto.get("precio"))} · {km_txt(auto.get("km"))}. Sale en «Autos disponibles».')
    pie(auto)
    if len(dest) < MAX_DESTACADOS:
        print(f'Destacados en el inicio: {len(dest)} de {MAX_DESTACADOS} (catalogo destacar {auto["id"]}).')


def detalle_venta(a):
    return (f'{a.get("marca")} {a.get("modelo")}' + (f' {a["version"]}' if a.get('version') else '') +
            f' · año {a.get("anio")} · {precio_txt(a.get("precio"))} · color {a.get("color_exterior") or "—"}'
            f' · placa termina en {a.get("placa_fin") or "—"}')


def cmd_vender(a):
    fecha = leer_fecha(a.fecha, []) if a.fecha else hoy()
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        exigir('vender', auto)
        if auto.get('estado') == 'vendido':
            raise Fallo(f'{titulo(auto)} ya estaba vendido (desde el {auto.get("vendido_el") or "—"}).')
        if not a.confirmar:
            print('Para confirmar la venta, muéstrale esto a quien lo pidió:')
            print(f'  {detalle_venta(auto)}')
            print(f'  Fecha de venta: {fecha}')
            print(f'Si lo confirma: catalogo vender {auto["id"]}' + (f' --fecha {fecha}' if a.fecha else '') + ' --confirmar')
            return
        era_destacado = auto.get('destacado') and auto.get('estado', 'disponible') == 'disponible'
        auto['estado'], auto['vendido_el'], auto['destacado'] = 'vendido', fecha, False
        auto.pop('previa', None)
        tocar(auto)
        guardar(datos, f'vender: {titulo(auto)} [{auto["id"]}] el {fecha}', a.nota)
        quedan = len(destacados_de(datos))
    print(f'Vendido: {detalle_venta(auto)} (fecha {fecha}).')
    print('Ya no sale en «Autos disponibles»; ahora está en «Autos vendidos».')
    if era_destacado:
        print(f'Era uno de los destacados del inicio: quedan {quedan} de {MAX_DESTACADOS}. '
              'Pregunta cuál auto lo reemplaza (catalogo destacar <auto>).')
    pie(auto)


def cmd_reactivar(a):
    cambios, avisos = leer_asignaciones(a.campos)
    datos_nuevos = dict(cambios)
    if set(datos_nuevos) - {'km', 'precio'}:
        raise Fallo('Al reactivar solo se actualizan el kilometraje y el precio; lo demás, con catalogo editar.')
    if datos_nuevos.get('km') in (None, NO_APLICA) or datos_nuevos.get('precio') is None:
        raise Fallo('Para volver a ponerlo en venta, pregunta el kilometraje y el precio actuales: '
                    f'catalogo reactivar {a.id} km=<kilometraje> precio=<precio>')
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        exigir('reactivar', auto)
        if auto.get('estado') != 'vendido':
            raise Fallo(f'{titulo(auto)} no está vendido.')
        antes = {c: estado_de(auto, c) for c in ('km', 'precio')}
        auto['estado'] = 'disponible'
        auto.pop('vendido_el', None)
        for campo, v in cambios:
            poner(auto, campo, v)
        tocar(auto)
        guardar(datos, f'reactivar: {titulo(auto)} [{auto["id"]}] · km; precio', a.nota)
    imprimir_avisos(avisos)
    print(f'De nuevo en venta: {titulo(auto)}. Sale en «Autos disponibles».')
    for c in ('km', 'precio'):
        print(f'  {ETIQUETAS[c]}: {mostrar_valor(c, antes[c])} → {mostrar_valor(c, estado_de(auto, c))}')
    pie(auto)


def cmd_ocultar(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        exigir('ocultar', auto)
        if auto.get('estado') in ('oculto', 'borrador'):
            raise Fallo(f'{titulo(auto)} ya no sale en el sitio ({auto.get("estado")}).')
        auto['estado'] = 'oculto'
        auto['destacado'] = False
        auto.pop('vendido_el', None)
        auto.setdefault('previa', secrets.token_urlsafe(16))
        tocar(auto)
        guardar(datos, f'ocultar: {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'Oculto: {titulo(auto)} ya no sale en ninguna página del sitio. '
          f'Para mostrarlo de nuevo: catalogo publicar {auto["id"]}')


def cmd_destacar(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        exigir('destacar', auto)
        quiere, sale = not a.no, None
        if quiere:
            if auto.get('estado', 'disponible') != 'disponible':
                raise Fallo(f'Solo se destacan autos publicados y en venta; {titulo(auto)} está {auto.get("estado")}.')
            if auto.get('destacado'):
                print(f'Sin cambios: {titulo(auto)} ya estaba destacado.')
                return
            dest = destacados_de(datos)
            if a.en_lugar_de:
                _, sale = buscar_auto(datos, a.en_lugar_de)
                if sale not in dest:
                    raise Fallo(f'{titulo(sale)} no está entre los destacados.')
                sale['destacado'] = False
                tocar(sale)
            elif len(dest) >= MAX_DESTACADOS:
                raise Fallo(f'Ya hay {len(dest)} destacados en el inicio (el máximo es {MAX_DESTACADOS}): ' +
                            '; '.join(f'{titulo(x)} [{x["id"]}]' for x in dest) +
                            f'. Pregunta cuál sale y usa: catalogo destacar {auto["id"]} --en-lugar-de <auto>')
        elif not auto.get('destacado'):
            print(f'Sin cambios: {titulo(auto)} no estaba destacado.')
            return
        auto['destacado'] = quiere
        tocar(auto)
        guardar(datos, (f'destacar: {titulo(auto)} [{auto["id"]}]' + (f' en lugar de [{sale["id"]}]' if sale else ''))
                if quiere else f'quitar destacado: {titulo(auto)} [{auto["id"]}]', a.nota)
        dest = destacados_de(datos)
    if quiere:
        print(f'Destacado en el inicio: {titulo(auto)}' + (f' (en lugar de {titulo(sale)}).' if sale else '.'))
    else:
        print(f'Ya no está destacado: {titulo(auto)}.')
    print(f'Destacados: {len(dest)} de {MAX_DESTACADOS}' +
          ('' if len(dest) >= MAX_DESTACADOS else '; el inicio completa con los últimos publicados') + '.')


def cmd_destacados(a):
    exigir('destacados')
    datos = cargar()
    dest = destacados_de(datos)
    print(f'Destacados en el inicio: {len(dest)} de {MAX_DESTACADOS}' + (':' if dest else '.'))
    for i, x in enumerate(dest, 1):
        print(f'  {i}. {titulo(x)} · {precio_txt(x.get("precio"))} [{x["id"]}]')
    if len(dest) < MAX_DESTACADOS:
        print(f'Faltan {MAX_DESTACADOS - len(dest)}: mientras tanto el inicio muestra los últimos publicados.')


def cmd_mover(a):
    with Candado():
        datos = cargar()
        i, auto = buscar_auto(datos, a.id)
        exigir('mover', auto)
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
    print(f'{titulo(auto)} quedó en la posición {destino} de {len(datos)} (es el orden de «Autos disponibles» y del inicio).')


def cmd_eliminar(a):
    with Candado():
        datos = cargar()
        i, auto = buscar_auto(datos, a.id, exacto=True)
        exigir('eliminar-borrador' if auto.get('estado') == 'borrador' else 'eliminar', auto)
        if not a.confirmar:
            print(f'Para confirmar que se borra, muéstrale esto a quien lo pidió:')
            print(f'  {detalle_venta(auto)} · {auto.get("estado", "disponible")}')
            if auto.get('estado') not in ('borrador', 'vendido'):
                print('  (Si se vendió, es mejor marcarlo vendido: así queda en «Autos vendidos».)')
            print(f'Si lo confirma: catalogo eliminar {auto["id"]} --confirmar')
            return
        datos.pop(i)
        guardar(datos, f'eliminar: {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'Eliminado: {titulo(auto)}. Si fue un error: catalogo deshacer (las fotos se guardan 30 días).')


def cmd_previa(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        exigir('previa', auto)
        if auto.get('estado', 'disponible') in PUBLICOS:
            print(f'{titulo(auto)} ya está publicado; su página: {enlace(auto)}')
            return
        if not auto.get('previa'):
            auto['previa'] = secrets.token_urlsafe(16)
            guardar(datos, f'previa: {titulo(auto)} [{auto["id"]}]', a.nota, 'Automático: sí')
        else:
            escribir_previas(datos)
    print(f'Vista previa de {titulo(auto)} (no está publicado; solo la ve quien tenga el enlace):')
    print(enlace_previa(auto))


def cmd_borradores(a):
    exigir('borradores')
    datos = [x for x in cargar() if x.get('estado') == 'borrador' and not de_otro_borrador(x)]
    if a.de:
        datos = [x for x in datos if x.get('creado_por') == a.de]
    meses = 'ene feb mar abr may jun jul ago sep oct nov dic'.split()
    corta = lambda d: f'{d.day} {meses[d.month - 1]}' if d else '—'
    if a.por_vencer:
        for x in datos:
            if DIAS_BORRADOR - dias_sin_cambios(x) == 1:
                f = faltantes(x, 4)
                print(f'⏳ Mañana se borra el borrador de {titulo(x)} (sin cambios desde el '
                      f'{corta(fecha_de(x.get("actualizado") or x.get("creado")))}).' +
                      (f' Le falta: {", ".join(f)}.' if f else ' Ya tiene todo: solo falta decir «Publicar».') +
                      ' Si lo quieres, sigue con él hoy; si no, no hagas nada.')
        return
    print(f'Borradores sin publicar: {len(datos)}' + (':' if datos else '.'))
    for x in datos:
        quedan = DIAS_BORRADOR - dias_sin_cambios(x)
        print(f'  {linea_auto(x)}')
        print(f'      se borra en {plural(max(quedan, 0), "día", "días")} si nadie lo toca'
              + (f' · subido por {quien_nombre(x.get("creado_por"))}' if ACTOR['rol'] != 'vendedor' else ''))


# -------------------------------------------------------------------- fotos
def abrir_imagen(contenido, nombre_archivo):
    """Valida la imagen y la deja derecha y en RGB. Devuelve (imagen, perfil de color, aviso)."""
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
            im.draft('RGB', (LADO_PORTADA * 2, LADO_PORTADA * 2))  # decodifica reducida: menos memoria
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
    return im, icc, aviso


def a_jpeg(im, icc, lado, calidad):
    from PIL import Image
    copia = im.copy()
    copia.thumbnail((lado, lado), getattr(Image, 'Resampling', Image).LANCZOS)
    salida = io.BytesIO()
    extra = {'icc_profile': icc} if icc else {}
    # Sin exif=: la foto publicada no lleva metadatos (ni la ubicación GPS del celular).
    copia.save(salida, 'JPEG', quality=calidad, optimize=True, progressive=True, **extra)
    return salida.getvalue()


def procesar_foto(contenido, nombre_archivo):
    """Foto de un auto: (grande, mediana, huella, aviso). Quita EXIF y GPS."""
    im, icc, aviso = abrir_imagen(contenido, nombre_archivo)
    grande = a_jpeg(im, icc, LADO_GRANDE, 82)
    mediana = a_jpeg(im, icc, LADO_MEDIANO, 78)
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
        exigir('foto', auto)
        fotos = list(auto.get('fotos') or [])
        nuevas, repetidas = [], 0
        for grande, mediana, huella in procesadas:
            web = f'{WEB_FOTOS}/{auto["id"]}/{huella}.jpg'
            if web in fotos or web in nuevas:
                repetidas += 1
                continue
            nuevas.append(web)
        if len(fotos) + len(nuevas) > MAX_FOTOS:
            raise Fallo(f'Un auto puede tener hasta {MAX_FOTOS} fotos; {titulo(auto)} ya tiene {len(fotos)} '
                        f'y llegaron {len(nuevas)}. Pregunta cuáles quitar (catalogo foto quitar) o cuáles no subir.')
        if nuevas:
            carpeta = FOTOS / auto['id']
            carpeta.mkdir(parents=True, exist_ok=True)
            for grande, mediana, huella in procesadas:
                if f'{WEB_FOTOS}/{auto["id"]}/{huella}.jpg' in nuevas:
                    escribir_atomico(carpeta / f'{huella}-m.jpg', mediana)
                    escribir_atomico(carpeta / f'{huella}.jpg', grande)
            auto['fotos'] = nuevas + fotos if a.portada else fotos + nuevas
            tocar(auto)
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
    n = len(auto.get('fotos') or [])
    if n < MIN_FOTOS:
        print(f'Faltan {MIN_FOTOS - n} {"foto" if MIN_FOTOS - n == 1 else "fotos"} para el mínimo de {MIN_FOTOS}.')
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
    exigir('foto-listar', auto)
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
        exigir('foto', auto)
        fotos = list(auto.get('fotos') or [])
        if not fotos:
            raise Fallo(f'{titulo(auto)} no tiene fotos.')
        quitar = set(range(1, len(fotos) + 1)) if a.todas else set(indices(a.numeros, len(fotos)))
        if not quitar:
            raise Fallo('Indica qué fotos quitar (por número, ver: catalogo foto listar) o usa --todas.')
        auto['fotos'] = [f for i, f in enumerate(fotos, 1) if i not in quitar]
        if auto.get('estado', 'disponible') == 'disponible' and len(auto['fotos']) < MIN_FOTOS and not a.forzar:
            raise Fallo(f'{titulo(auto)} está publicado y quedaría con {len(auto["fotos"])} fotos (mínimo {MIN_FOTOS}). '
                        'Pide las fotos que lo reemplazan primero, o repite con --forzar si de verdad deben salir.')
        tocar(auto)
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
        exigir('foto', auto)
        fotos = list(auto.get('fotos') or [])
        orden = indices(a.numeros, len(fotos))
        if not orden:
            raise Fallo('Indica el nuevo orden, por ejemplo: catalogo foto orden <id> 3 1 2')
        nuevo = [fotos[n - 1] for n in orden] + [f for i, f in enumerate(fotos, 1) if i not in orden]
        if nuevo == fotos:
            print('Sin cambios: las fotos ya estaban en ese orden.')
            return
        auto['fotos'] = nuevo
        tocar(auto)
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
        exigir('linea', auto)
        linea = auto.setdefault('historial', {}).setdefault('linea', [])
        linea.append({'titulo': t, 'texto': x})
        tocar(auto)
        guardar(datos, f'linea: +1 hito en {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'Hito agregado a la línea de tiempo de {titulo(auto)} (ahora tiene {len(linea)}).')


def cmd_linea_quitar(a):
    with Candado():
        datos = cargar()
        _, auto = buscar_auto(datos, a.id)
        exigir('linea', auto)
        linea = (auto.get('historial') or {}).get('linea') or []
        quitar = set(indices([a.numero], len(linea))) if linea else set()
        if not quitar:
            raise Fallo(f'{titulo(auto)} no tiene hitos en la línea de tiempo.')
        auto['historial']['linea'] = [p for i, p in enumerate(linea, 1) if i not in quitar]
        if not auto['historial']['linea']:
            auto['historial'].pop('linea')
        tocar(auto)
        guardar(datos, f'linea: -1 hito en {titulo(auto)} [{auto["id"]}]', a.nota)
    print(f'Hito {a.numero} quitado de {titulo(auto)}.')


# ------------------------------------------------------------------ portada
# El bloque principal del inicio: un texto corto arriba (hoy «BMW»), el título
# grande (hoy «Serie 7 2026»), el fondo (foto o video) y a dónde lleva «Ver
# más». Lo que no se cambie sigue como lo trae el diseño del sitio.
def cmd_portada_ver(a):
    exigir('portada-ver')
    po = cargar_sitio().get('portada') or {}
    medio = po.get('medio') or {}
    base = sitio()
    print('Portada del inicio' + (f' ({base}/)' if base else '') + ':')
    print(f'  Texto corto de arriba: {po.get("texto") or "BMW (el original del diseño)"}')
    print(f'  Título: {(po.get("titulo") or "Serie 7 / 2026 (el original del diseño)").replace(chr(10), " / ")}')
    print('  Fondo: ' + {'video': 'un video propio', 'foto': 'una foto propia'}.get(medio.get('tipo'),
                                                                                 'el video original del sitio'))
    if medio.get('ruta'):
        print(f'    {base + "/" if base else ""}{medio["ruta"]}')
    if po.get('auto'):
        auto = next((x for x in cargar() if x.get('id') == po['auto']), None)
        print(f'  «Ver más» lleva a: {titulo(auto) + " · " + enlace(auto) if auto else po["auto"] + " (ya no existe)"}')
    else:
        print('  «Ver más» lleva a: Autos disponibles')


def cmd_portada_textos(a):
    exigir('portada')
    cambios = {}
    for par in a.campos:
        if '=' not in par:
            raise Fallo(f'«{par}» no tiene la forma campo=valor (texto=…, titulo=… o auto=…).')
        k, v = par.split('=', 1)
        k = {'texto': 'texto', 'antetitulo': 'texto', 'linea': 'texto', 'marca': 'texto', 'titulo': 'titulo',
             'auto': 'auto', 'enlace': 'auto', 'ver_mas': 'auto'}.get(clave(k))
        if not k:
            raise Fallo('En la portada se cambian: texto (la línea corta de arriba), titulo y auto (a dónde lleva «Ver más»).')
        v = v.strip()
        if v == '' or clave(v) in ('borrar', 'quitar', 'original', 'ninguno'):
            cambios[k] = None
        elif k == 'titulo':
            v = limpiar_texto(v.replace(' | ', '\n').replace('|', '\n'), 60, multilinea=True)
            if v.count('\n') > 1:
                raise Fallo('El título de la portada va en una o dos líneas (sepáralas con «|»).')
            cambios[k] = v
        elif k == 'texto':
            cambios[k] = limpiar_texto(v, 40)
        else:
            cambios[k] = v
    if not cambios:
        raise Fallo('Indica qué cambiar, por ejemplo: catalogo portada textos texto=Mazda "titulo=CX-5 | 2022"')
    with Candado():
        if cambios.get('auto'):
            _, auto = buscar_auto(cargar(), cambios['auto'])
            if auto.get('estado', 'disponible') != 'disponible':
                raise Fallo(f'«Ver más» solo puede llevar a un auto publicado y en venta; {titulo(auto)} no lo está.')
            cambios['auto'] = auto['id']
        s = cargar_sitio()
        po = dict(s.get('portada') or {})
        for k, v in cambios.items():
            if v is None:
                po.pop(k, None)
            else:
                po[k] = v
        if po:
            s['portada'] = po
        else:
            s.pop('portada', None)
        guardar_sitio(s, 'portada: ' + ', '.join(cambios), a.nota)
    print('Portada actualizada:')
    for k, v in cambios.items():
        nombre_k = {'texto': 'Texto corto', 'titulo': 'Título', 'auto': '«Ver más» lleva a'}[k]
        print(f'  {nombre_k}: ' + (v.replace('\n', ' / ') if v else 'el original'))
    print(f'Mírala en: {sitio() or "el inicio"}/')


def medio_en_disco(contenido, extension):
    huella = hashlib.sha256(contenido).hexdigest()[:16]
    MEDIOS.mkdir(exist_ok=True)
    destino = MEDIOS / f'{huella}.{extension}'
    if not destino.exists():
        escribir_atomico(destino, contenido)
    return f'{WEB_MEDIOS}/{huella}.{extension}'


def medir_video(ruta):
    """(ancho, alto, segundos) del video con ffprobe; None si no se pudo."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        return None
    try:
        r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                            'stream=width,height:stream_side_data=rotation:format=duration', '-of', 'json', str(ruta)],
                           capture_output=True, text=True, timeout=60)
        info = json.loads(r.stdout or '{}')
        st = (info.get('streams') or [{}])[0]
        ancho, alto = int(st.get('width') or 0), int(st.get('height') or 0)
        giro = abs(int(float(((st.get('side_data_list') or [{}])[0]).get('rotation') or 0)))
        if giro in (90, 270):
            ancho, alto = alto, ancho
        return ancho, alto, float((info.get('format') or {}).get('duration') or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def procesar_video(contenido, nombre_archivo):
    """Deja el video listo para el fondo de la portada: MP4 (H.264) liviano, sin
    audio ni metadatos (ubicación GPS del celular), de hasta 1920 px y 60 s.
    Devuelve (video, póster jpg, avisos)."""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise Fallo('Falta ffmpeg en el servidor para preparar videos. El administrador lo instala con: '
                    'mendiautos actualizar --forzar')
    if len(contenido) > MAX_BYTES_VIDEO:
        raise Fallo(f'{nombre_archivo}: el video pesa más de {MAX_BYTES_VIDEO // 1048576} MB.')
    avisos = []
    with tempfile.TemporaryDirectory(prefix='catalogo-video-') as tmp:
        entrada, salida, poster = Path(tmp) / 'entrada', Path(tmp) / 'video.mp4', Path(tmp) / 'poster.jpg'
        entrada.write_bytes(contenido)
        medida = medir_video(entrada)
        if medida:
            ancho, alto, segundos = medida
            if not ancho or not alto:
                raise Fallo(f'{nombre_archivo}: no es un video válido.')
            if alto > ancho:
                avisos.append('El video es vertical: en computador se verá recortado arriba y abajo. '
                              'Para la portada queda mejor uno horizontal.')
            if segundos > MAX_SEGUNDOS_VIDEO:
                avisos.append(f'El video dura {round(segundos)} s: se usaron los primeros {MAX_SEGUNDOS_VIDEO} s.')
        base = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y']
        try:
            r = subprocess.run(base + ['-i', str(entrada), '-t', str(MAX_SEGUNDOS_VIDEO), '-map', '0:v:0', '-an',
                                       '-sn', '-dn', '-map_metadata', '-1', '-map_chapters', '-1',
                                       '-vf', "scale='min(1920,iw)':-2:flags=lanczos", '-r', '30',
                                       '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26',
                                       '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(salida)],
                               capture_output=True, timeout=900)
        except subprocess.TimeoutExpired:
            raise Fallo(f'{nombre_archivo}: el video tardó demasiado en procesarse; prueba con uno más corto.')
        if r.returncode or not salida.exists() or salida.stat().st_size < 1024:
            raise Fallo(f'{nombre_archivo}: no pude procesar el video (¿es un video válido?).')
        subprocess.run(base + ['-i', str(salida), '-frames:v', '1', '-vf', "scale='min(1600,iw)':-2",
                               '-q:v', '4', str(poster)], capture_output=True, timeout=120)
        video = salida.read_bytes()
        cartel = poster.read_bytes() if poster.exists() and poster.stat().st_size > 0 else b''
    return video, cartel, avisos


def cmd_portada_medio(a, entradas):
    exigir('portada')
    nombre_archivo, contenido = entradas[0]
    avisos = []
    if a.tipo == 'foto':
        im, icc, aviso = abrir_imagen(contenido, nombre_archivo)
        if aviso:
            avisos.append(aviso)
        if im.size[1] > im.size[0]:
            avisos.append('La foto es vertical: en computador se verá recortada. Para la portada queda mejor una horizontal.')
        medio = {'tipo': 'foto', 'ruta': medio_en_disco(a_jpeg(im, icc, LADO_PORTADA, 84), 'jpg')}
    else:
        video, cartel, avisos = procesar_video(contenido, nombre_archivo)
        medio = {'tipo': 'video', 'ruta': medio_en_disco(video, 'mp4')}
        if cartel:
            medio['poster'] = medio_en_disco(cartel, 'jpg')
    with Candado():
        s = cargar_sitio()
        po = dict(s.get('portada') or {})
        po['medio'] = medio
        s['portada'] = po
        guardar_sitio(s, f'portada: {"video" if a.tipo == "video" else "foto"} de fondo', a.nota)
    imprimir_avisos(avisos)
    print(f'Listo: el fondo de la portada del inicio ahora es {"este video" if a.tipo == "video" else "esta foto"}.'
          + (f' ({len(contenido) / 1048576:.1f} MB → {(MEDIOS / Path(medio["ruta"]).name).stat().st_size / 1048576:.1f} MB)'
             if a.tipo == 'video' else ''))
    print(f'Mírala en: {sitio() or "el inicio"}/')


def cmd_portada_original(a):
    exigir('portada')
    with Candado():
        s = cargar_sitio()
        po = dict(s.get('portada') or {})
        quitar = ['medio'] if a.solo_fondo else ['texto', 'titulo', 'auto'] if a.solo_textos else list(po)
        if not any(k in po for k in quitar):
            print('Sin cambios: eso ya estaba como el original del sitio.')
            return
        for k in quitar:
            po.pop(k, None)
        if po:
            s['portada'] = po
        else:
            s.pop('portada', None)
        guardar_sitio(s, 'portada: vuelve a la original' + (' (fondo)' if a.solo_fondo else ' (textos)' if a.solo_textos else ''),
                      a.nota)
    print('La portada volvió a ' + ('su fondo original.' if a.solo_fondo else 'sus textos originales.' if a.solo_textos
                                    else 'la original del sitio (video y textos).'))


# ------------------------------------------------- videos de otros servicios
def cmd_servicios_ver(a):
    exigir('servicios-ver')
    sv = cargar_sitio().get('servicios') or {}
    print('Videos de «Otros servicios» (YouTube):')
    for k, nombre_s in SERVICIOS.items():
        print(f'  {nombre_s} ({k}): {sv.get(k) or "sin video"}')


def cmd_servicios_video(a):
    exigir('servicios')
    k = clave(a.servicio)
    k = SERVICIOS_ALIAS.get(k, k)
    if k not in SERVICIOS:
        raise Fallo('El servicio es uno de: ' + ', '.join(SERVICIOS) + '.')
    quitar = clave(a.enlace) in ('borrar', 'quitar', 'ninguno')
    nuevo = None if quitar else leer_youtube(a.enlace)
    with Candado():
        s = cargar_sitio()
        sv = dict(s.get('servicios') or {})
        if sv.get(k) == nuevo:
            print(f'Sin cambios: {SERVICIOS[k]} ya tenía ese video.')
            return
        if nuevo:
            sv[k] = nuevo
        else:
            sv.pop(k, None)
        if sv:
            s['servicios'] = sv
        else:
            s.pop('servicios', None)
        guardar_sitio(s, f'servicios: video de {k}' + (' (quitado)' if quitar else ''), a.nota)
    print(f'{SERVICIOS[k]}: ' + (f'ahora muestra {nuevo}' if nuevo else 'sin video') +
          f'. Página: {sitio() + "/" if sitio() else ""}OtrosServicios.dc.html')


MESES = 'ene feb mar abr may jun jul ago sep oct nov dic'.split()
MESES_LARGOS = ('enero febrero marzo abril mayo junio julio agosto septiembre octubre '
                'noviembre diciembre').split()


def corta(d):
    return f'{d.day} {MESES[d.month - 1]}' if d else '—'


def lista_autos(autos, extra=lambda x: '', maximo=10):
    return ''.join(f'\n  · {titulo(x)}{extra(x)}' for x in autos[:maximo]) + \
        (f'\n  · … y {len(autos) - maximo} más' if len(autos) > maximo else '')


def cmd_resumen(a):
    """Informe corto del catálogo (lo pidieron por chat o lo manda una tarea)."""
    exigir('resumen')
    datos = cargar()
    hoy_ = hoy_d()
    desde = hoy_ - dt.timedelta(days=a.dias)
    disp = [x for x in datos if x.get('estado', 'disponible') == 'disponible']
    vendidos = [x for x in datos if x.get('estado') == 'vendido' and (fecha_de(x.get('vendido_el')) or dt.date.min) >= desde]
    nuevos = [x for x in disp if (fecha_de(x.get('publicado') or x.get('creado')) or dt.date.min) >= desde]
    incompletos = [x for x in disp if faltantes(x)]
    quietos = [x for x in disp if fecha_de(x.get('publicado') or x.get('creado')) and
               (hoy_ - fecha_de(x.get('publicado') or x.get('creado'))).days > 60]
    borradores = [x for x in datos if x.get('estado') == 'borrador']
    print(f'Catálogo Mendiautos · {corta(desde)} al {corta(hoy_)}')
    print(f'{plural(len(disp), "auto disponible", "autos disponibles")} ({len(destacados_de(datos))} destacados) · '
          f'{plural(len(vendidos), "vendido", "vendidos")} y {plural(len(nuevos), "publicado", "publicados")} '
          f'en estos {a.dias} días.')
    if vendidos:
        print('Vendidos:' + lista_autos(vendidos, lambda x: f' ({corta(fecha_de(x["vendido_el"]))})'))
    if nuevos:
        print('Publicados:' + lista_autos(nuevos))
    if incompletos:
        print('Con datos o fotos por completar:' + lista_autos(incompletos, lambda x: f' (falta: {", ".join(faltantes(x, 3))})'))
    if quietos:
        print('Publicados hace más de 60 días:' + lista_autos(
            quietos, lambda x: f' (desde el {corta(fecha_de(x.get("publicado") or x.get("creado")))})'))
    if borradores:
        print('Borradores sin publicar:' + lista_autos(borradores))
    if not incompletos:
        print('Todos los autos disponibles tienen sus datos y fotos. 👍')


# ------------------------------------------------------------------ informes
def visitas_entre(desde, hasta):
    """Suma los conteos diarios de visitas (los escribe mendiautos-visitas cada noche)."""
    total = {'vistas': 0, 'visitantes': 0, 'autos': {}, 'dias': 0}
    d = desde
    while d <= hasta:
        try:
            dia = json.loads((VISITAS / f'{d.isoformat()}.json').read_text('utf-8'))
        except (OSError, ValueError):
            dia = None
        if isinstance(dia, dict):
            total['dias'] += 1
            total['vistas'] += int(dia.get('vistas') or 0)
            total['visitantes'] += int(dia.get('visitantes') or 0)
            for k, v in (dia.get('autos') or {}).items():
                if isinstance(v, int):
                    total['autos'][k] = total['autos'].get(k, 0) + v
        d += dt.timedelta(days=1)
    return total


def periodo(a):
    hoy_ = hoy_d()
    if a.mes:
        fin = hoy_.replace(day=1) - dt.timedelta(days=1)      # el mes anterior completo
        return fin.replace(day=1), fin, f'{MESES_LARGOS[fin.month - 1]} de {fin.year}', 'mensual'
    if a.desde:
        desde = fecha_de(a.desde)
        hasta = fecha_de(a.hasta) if a.hasta else hoy_ - dt.timedelta(days=1)
        if not desde or not hasta or desde > hasta:
            raise Fallo('Usa --desde AAAA-MM-DD [--hasta AAAA-MM-DD].')
        return desde, hasta, f'{corta(desde)} al {corta(hasta)}', 'del periodo'
    hasta = hoy_ - dt.timedelta(days=1)                       # la semana que terminó ayer
    desde = hasta - dt.timedelta(days=6)
    return desde, hasta, f'{corta(desde)} al {corta(hasta)}', 'semanal'


def promedio(valores):
    return round(sum(valores) / len(valores)) if valores else None


def cmd_informe(a):
    """Informe de movimiento para el gerente y el administrador (semanal o mensual)."""
    exigir('informe')
    datos = cargar()
    desde, hasta, nombre_periodo, tipo = periodo(a)
    en = lambda f: f is not None and desde <= f <= hasta
    entrada = lambda x: fecha_de(x.get('publicado') or x.get('creado'))
    publicos = [x for x in datos if x.get('estado', 'disponible') in PUBLICOS]
    entraron = [x for x in publicos if en(entrada(x))]
    vendidos = [x for x in datos if x.get('estado') == 'vendido' and en(fecha_de(x.get('vendido_el')))]
    inventario = [x for x in datos if x.get('estado', 'disponible') == 'disponible']
    dias_venta = [(fecha_de(x['vendido_el']) - entrada(x)).days for x in vendidos
                  if entrada(x) and fecha_de(x.get('vendido_el'))]
    dias_stock = [(hoy_d() - entrada(x)).days for x in inventario if entrada(x)]
    incompletos = [x for x in inventario if faltantes(x)]
    print(f'📊 Informe {tipo} de Mendiautos · {nombre_periodo}')
    print(f'🚗 Entraron {len(entraron)} · Vendidos {len(vendidos)} · En inventario hoy {len(inventario)}')
    if vendidos:
        print('Vendidos:' + lista_autos(vendidos, lambda x: f' · {precio_txt(x.get("precio"))}'
                                        f' ({corta(fecha_de(x["vendido_el"]))})'))
    if entraron:
        print('Entraron:' + lista_autos(entraron))
    p_stock, p_venta = promedio(dias_stock), promedio(dias_venta)
    if p_stock is not None or p_venta is not None:
        print('⏱ Días promedio en inventario: ' + ', '.join(x for x in (
            f'{p_stock} (autos disponibles hoy)' if p_stock is not None else '',
            f'{p_venta} hasta venderse (vendidos en el periodo)' if p_venta is not None else '') if x))
    v = visitas_entre(desde, hasta)
    if v['dias']:
        por_id = {x['id']: x for x in datos}
        top = sorted(((n, k) for k, n in v['autos'].items() if k in por_id), reverse=True)[:5]
        print(f'👀 Visitas a la página: {miles(v["vistas"])} · visitantes: {miles(v["visitantes"])}' +
              (f' (datos de {v["dias"]} de {(hasta - desde).days + 1} días)' if v['dias'] < (hasta - desde).days + 1 else ''))
        if top:
            print('Autos más vistos:' + ''.join(f'\n  {i}. {titulo(por_id[k])} ({miles(n)})' for i, (n, k) in enumerate(top, 1)))
    else:
        print('👀 Visitas: todavía no hay conteos de estos días.')
    if incompletos:
        print(f'⚠️ Sin fotos o con datos incompletos ({len(incompletos)}):' +
              lista_autos(incompletos, lambda x: f' (falta: {", ".join(faltantes(x, 3))})', 8))
    else:
        print('✅ Todos los autos disponibles tienen sus fotos y datos.')


# ----------------------------------------------------------------- historial
def registros(n=200):
    salida = git('log', f'-n{n}', '--format=%H%x1f%ad%x1f%s%x1f%b%x1e', '--date=format-local:%Y-%m-%d %H:%M',
                 '--', 'inventario.json', 'sitio.json', check=False)
    res = []
    for r in salida.split('\x1e'):
        partes = r.strip('\n').split('\x1f')
        if len(partes) == 4:
            reg = dict(zip(('hash', 'fecha', 'asunto', 'cuerpo'), partes))
            m = re.search(r'^Por: (\S+)', reg['cuerpo'], re.M)
            reg['por'] = m.group(1) if m else ''
            res.append(reg)
    return res


def cmd_historial(a):
    exigir('historial')
    regs = registros(max(1, min(a.n, 500)))
    if not regs:
        print('Todavía no hay cambios registrados.')
        return
    print(f'Últimos {len(regs)} cambios (hora de Colombia):')
    for r in regs:
        nota = re.search(r'^Nota: (.*)$', r['cuerpo'], re.M)
        quien = re.search(r'^Por: \S+(?: \((.*)\))?$', r['cuerpo'], re.M)
        print(f'  {r["hash"][:8]}  {r["fecha"]}  {r["asunto"]}' +
              (f'  · {quien.group(1) or "equipo"}' if quien else '') + (f'  ({nota.group(1)})' if nota else ''))


def version_en(h):
    try:
        return normalizar(json.loads(git('show', f'{h}:inventario.json')))
    except (Fallo, ValueError):
        return None


def sitio_en(h):
    try:
        s = json.loads(git('show', f'{h}:sitio.json'))
        return s if isinstance(s, dict) else None
    except (Fallo, ValueError):
        return None


def archivos_de(h):
    return set(git('show', '--name-only', '--format=', h, check=False).split())


def cmd_precios(a):
    exigir('precios')
    datos = cargar()
    _, auto = buscar_auto(datos, a.id)
    cambios, anterior = [], object()
    for r in reversed(registros(500)):
        if f'[{auto["id"]}]' not in r['asunto']:
            continue
        version = version_en(r['hash']) or []
        este = next((x for x in version if x.get('id') == auto['id']), None)
        if este is None:
            continue
        p = este.get('precio')
        if p is None and not cambios:
            continue                # el borrador todavía no tenía precio
        if p != anterior:
            cambios.append((r['fecha'][:10], p))
            anterior = p
    print(f'Precios de {titulo(auto)}' + (':' if cambios else ': sin registros.'))
    for fecha, p in cambios:
        print(f'  {fecha}  {precio_txt(p)}')


def cmd_deshacer(a):
    with Candado():
        deshechos, objetivo = set(), None
        for r in registros(400):
            m = re.search(r'^Deshace: ([0-9a-f]{40})$', r['cuerpo'], re.M)
            if m:
                deshechos.add(m.group(1))
                continue
            if r['hash'] in deshechos or r['asunto'].startswith('previa:'):
                continue
            if r['asunto'].startswith('iniciar'):
                break
            if ACTOR['id'] and r['por'] != ACTOR['id']:
                continue            # cada persona deshace sus propios cambios
            objetivo = r
            break
        if not objetivo:
            raise Fallo('No hay cambios tuyos para deshacer.' if ACTOR['id'] else 'No hay cambios para deshacer.')
        exigir('deshacer')
        if a.forzar and ACTOR['rol'] == 'vendedor':
            raise Fallo('Forzar un deshacer que pisa cambios de otros lo hacen el gerente o el administrador.')
        if 'sitio.json' in archivos_de(objetivo['hash']):
            despues, antes = sitio_en(objetivo['hash']), sitio_en(objetivo['hash'] + '^') or {}
            if despues is None:
                raise Fallo('No pude leer ese cambio en el historial.')
            if cargar_sitio() != despues and not a.forzar:
                raise Fallo('No puedo deshacer «' + objetivo['asunto'] + '» porque después hubo otros cambios en la '
                            'portada o los videos. Para forzarlo (se pierden esos cambios) usa --forzar.')
            guardar_sitio(antes, f'deshacer: {objetivo["asunto"]}', a.nota, f'Deshace: {objetivo["hash"]}')
            print(f'Deshecho: {objetivo["asunto"]} (del {objetivo["fecha"]}).')
            return
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
def visibles(datos):
    return [publico(a) for a in datos if a.get('estado', 'disponible') in PUBLICOS]


def medios_de(sitio_datos):
    m = ((sitio_datos or {}).get('portada') or {}).get('medio') or {}
    return {x for x in (m.get('ruta'), m.get('poster')) if isinstance(x, str)}


def ruta_medio(web):
    m = RE_MEDIO.match(web)
    return MEDIOS / f'{m.group(1)}.{m.group(2)}' if m else None


def revisar():
    """Revisa datos, fotos, portada y los .js del sitio (los regenera si quedaron desfasados)."""
    datos = cargar()
    sitio_datos = cargar_sitio()
    p = problemas(datos) + problemas_sitio(sitio_datos)
    for auto in datos:
        for f in (auto.get('fotos') or []) if isinstance(auto, dict) else []:
            local = ruta_local(f) if isinstance(f, str) else None
            if local and not (local.exists() and local.with_name(local.stem + '-m.jpg').exists()):
                p.append(f'{auto.get("id")}: falta el archivo de la foto {f}')
    for web in medios_de(sitio_datos):
        local = ruta_medio(web)
        if local and not local.exists():
            p.append(f'portada: falta el archivo {web}')
    try:
        js_ok = datos_de_js(JS_F.read_text('utf-8')) == json.loads(json.dumps(visibles(datos)))
    except (OSError, Fallo):
        js_ok = False
    regenerados = []
    if not js_ok and not problemas(datos):
        with Candado():
            escribir_atomico(JS_F, js_de(cargar()))
        regenerados.append('inventario.js')
    try:
        sitio_ok = SITIO_JS.read_bytes().split(b'\n', 1)[1] == js_sitio(sitio_datos).split(b'\n', 1)[1]
    except (OSError, IndexError):
        sitio_ok = False
    if not sitio_ok and not problemas_sitio(sitio_datos):
        with Candado():
            escribir_atomico(SITIO_JS, js_sitio(cargar_sitio()))
        regenerados.append('sitio.js')
    if regenerados:
        with Candado():
            escribir_previas(cargar())
        print(' y '.join(regenerados) + ' no coincidía' + ('n' if len(regenerados) > 1 else '') +
              ' con los datos y se regeneró' + ('n' if len(regenerados) > 1 else '') + '.')
    if p:
        print('Problemas encontrados:\n  ' + '\n  '.join(p))
        return False
    cuenta = {e: sum(1 for x in datos if x.get('estado', 'disponible') == e) for e in ESTADOS}
    fotos = sum(len(x.get('fotos') or []) for x in datos)
    print(f'Catálogo en orden: {plural(len(datos), "auto", "autos")} '
          f'({plural(cuenta["disponible"], "disponible", "disponibles")}, '
          f'{plural(cuenta["vendido"], "vendido", "vendidos")}' +
          (f', {plural(cuenta["oculto"], "oculto", "ocultos")}' if cuenta['oculto'] else '') +
          (f', {plural(cuenta["borrador"], "borrador", "borradores")}' if cuenta['borrador'] else '') +
          f'), {plural(fotos, "foto", "fotos")}.')
    return True


def cmd_validar(a):
    exigir('validar')
    if not revisar():
        raise SystemExit(1)


def cmd_migrar(a):
    """Pone al día los datos y los .js del sitio con esta versión del comando (lo corre mendiautos.sh)."""
    if not JSON_F.exists():
        return
    gi = DATOS / '.gitignore'
    if gi.exists() and '!sitio.json' not in gi.read_text('utf-8'):
        gi.write_text('# Solo se versionan inventario.json y sitio.json\n*\n!inventario.json\n!sitio.json\n!.gitignore\n')
    with Candado():
        crudo = json.loads(JSON_F.read_text('utf-8'))
        datos = normalizar(json.loads(JSON_F.read_text('utf-8')))
        cambios = []
        if crudo != datos:
            cambios.append('se quitó ' + ', '.join(sorted({k for x in crudo if isinstance(x, dict)
                                                          for k in x if k in RETIRADOS})))
        # El inicio muestra 5 destacados: los que sobren (catálogos anteriores) dejan de serlo.
        sobran = destacados_de(datos)[MAX_DESTACADOS:]
        for x in sobran:
            x['destacado'] = False
        if sobran:
            cambios.append(f'solo {MAX_DESTACADOS} destacados (dejan de serlo: ' + ', '.join(titulo(x) for x in sobran) + ')')
        if cambios:
            guardar(datos, 'migrar: ' + '; '.join(cambios), '', 'Automático: sí')
            print('Catálogo actualizado: ' + '; '.join(cambios) + '.')
    revisar()


def vencer_borradores():
    with Candado():
        datos = cargar()
        vencidos = [x for x in datos if x.get('estado') == 'borrador' and dias_sin_cambios(x) >= DIAS_BORRADOR]
        if not vencidos:
            return
        ids = {x['id'] for x in vencidos}
        guardar([x for x in datos if x.get('id') not in ids],
                'borradores vencidos: ' + ', '.join(f'{titulo(x)} [{x["id"]}]' for x in vencidos),
                '', 'Automático: sí')
    print(f'Borradores sin cambios en {DIAS_BORRADOR} días, borrados: ' + ', '.join(titulo(x) for x in vencidos) + '.')


def fotos_de_version(version):
    return {f for x in version or [] if isinstance(x, dict) for f in (x.get('fotos') or []) if isinstance(f, str)}


def referencias(dias):
    refs = fotos_de_version(cargar()) | medios_de(cargar_sitio())
    for archivo, leer, extraer in (('inventario.json', version_en, fotos_de_version),
                                   ('sitio.json', sitio_en, medios_de)):
        hashes = git('log', f'--since={dias}.days.ago', '--format=%H', '--', archivo, check=False).split()
        previo = git('log', '-n1', f'--until={dias}.days.ago', '--format=%H', '--', archivo, check=False).split()
        for h in hashes + previo:
            refs |= extraer(leer(h))
    return refs


def cmd_limpiar(a):
    with Candado():
        refs = referencias(a.dias)
        limite = time.time() - a.dias * 86400
        borradas = liberado = 0
        for carpeta in (FOTOS.iterdir() if FOTOS.is_dir() else []):
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
        for f in (MEDIOS.iterdir() if MEDIOS.is_dir() else []):
            if f.is_file() and f'{WEB_MEDIOS}/{f.name}' not in refs and f.stat().st_mtime <= limite:
                liberado += f.stat().st_size
                f.unlink()
                borradas += 1
    print(f'Limpieza: {plural(borradas, "archivo borrado", "archivos borrados")} '
          f'({liberado / 1048576:.1f} MB) de fotos y videos sin usar hace más de {a.dias} días.')


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
    vencer_borradores()
    cmd_limpiar(a)
    cmd_respaldar(a)  # se respalda aunque haya problemas: justo entonces sirve tener la copia
    if not bien:
        raise SystemExit(1)


def importar_archivo(ruta):
    texto = Path(ruta).read_text('utf-8')
    try:
        datos = normalizar(json.loads(texto) if ruta.endswith('.json') else datos_de_js(texto))
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
        (DATOS / '.gitignore').write_text('# Solo se versionan inventario.json y sitio.json\n*\n'
                                          '!inventario.json\n!sitio.json\n!.gitignore\n')
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
EXT_VIDEO = ('.mp4', '.mov', '.m4v', '.webm', '.mkv', '.3gp', '.avi')


def recientes(n, minutos, carpeta, subcarpetas, extensiones, que):
    """Los n últimos archivos que recibió Hermes (Telegram los deja en su caché)."""
    home = Path(os.environ.get('HERMES_HOME') or Path.home() / '.hermes')
    dirs = [Path(carpeta)] if carpeta else [home / d for d in subcarpetas]
    limite = time.time() - minutos * 60
    halladas = []
    for d in dirs:
        if d.is_dir():
            for f in d.iterdir():
                try:
                    st = f.stat()
                except OSError:
                    continue
                if f.is_file() and f.suffix.lower() in extensiones and st.st_mtime >= limite:
                    halladas.append((st.st_mtime, str(f)))
    halladas.sort()
    if len(halladas) < n:
        raise Fallo(f'Solo encontré {len(halladas)} {que} recibidos en los últimos {minutos} minutos y '
                    f'pediste {n}. Pide que los envíen otra vez.')
    return [f for _, f in halladas[-n:]]


def fotos_recientes(n, minutos, carpeta=None):
    return recientes(n, minutos, carpeta, ('cache/images', 'cache/documents', 'image_cache', 'document_cache'),
                     EXT_IMAGEN, 'archivos de foto')


def videos_recientes(minutos, carpeta=None):
    return recientes(1, minutos, carpeta, ('cache/videos', 'cache/video', 'cache/documents', 'video_cache',
                                           'document_cache'), EXT_VIDEO, 'videos')


def leer_archivos(rutas, max_bytes=MAX_BYTES_FOTO, que='foto'):
    if not rutas:
        raise Fallo(f'Indica {"las fotos" if que == "foto" else "el archivo"} (rutas de archivo) o usa --ultimas.')
    if len(rutas) > MAX_ARCHIVOS:
        raise Fallo(f'Máximo {MAX_ARCHIVOS} fotos por comando.')
    res, total = [], 0
    for r in rutas:
        ruta = Path(r).expanduser()
        if not ruta.is_file():
            raise Fallo(f'No encuentro el archivo {r}. Lo que llega por Telegram se borra del caché a las '
                        '24 horas: si es más viejo, pide que lo envíen de nuevo.')
        tam = ruta.stat().st_size
        if tam > max_bytes:
            raise Fallo(f'{ruta.name}: {"la foto" if que == "foto" else "el archivo"} pesa más de {max_bytes // 1048576} MB.')
        total += tam
        if total > MAX_BYTES_TOTAL:
            raise Fallo('Son demasiadas fotos pesadas para un solo comando; envíalas en partes.')
        res.append((ruta.name, ruta.read_bytes()))
    return res


def empaquetar(entradas):
    partes = [b'%d\n' % len(entradas)]
    for nombre_archivo, contenido in entradas:
        n = nombre_archivo.encode('utf-8')[:200]
        partes += [b'%d %d\n' % (len(n), len(contenido)), n, contenido]
    return b''.join(partes)


def desempaquetar(flujo, max_bytes=MAX_BYTES_FOTO):
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
            if not (0 <= ln <= 200 and 0 < lc <= max_bytes and total <= MAX_BYTES_TOTAL):
                raise ValueError
            n = flujo.read(ln).decode('utf-8', 'replace')
            c = flujo.read(lc)
            if len(c) != lc:
                raise ValueError
            res.append((CONTROL.sub('', n) or 'archivo', c))
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


SOLO_ADMIN = {'iniciar', 'importar', 'respaldar', 'mantenimiento', 'limpiar', 'migrar'}


# ------------------------------------------------------------------- parser
class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f'Error: {message}\nAyuda: catalogo --help\n')


def construir_parser():
    comun = argparse.ArgumentParser(add_help=False)
    comun.add_argument('--nota', default='', help='texto que queda en el historial (por qué se hizo)')
    comun.add_argument('--por', default='', metavar='ID', help='ID de Telegram de quien pide el cambio (lo pone el asistente)')
    p = Parser(prog='catalogo', description='Administra el catálogo de autos del sitio de Mendiautos.',
               epilog='Donde se pide <auto> sirve el id exacto o palabras que lo identifiquen sin ambigüedad '
                      '(por ejemplo «duster 2023»). Un auto nuevo queda como borrador hasta «catalogo publicar».')
    sub = p.add_subparsers(dest='comando', metavar='comando', parser_class=Parser)
    sub.required = True

    def nuevo(nombre_cmd, ayuda, func=None, subgrupo=None):
        s = (subgrupo or sub).add_parser(nombre_cmd, help=ayuda, description=ayuda, parents=[comun])
        if func:
            s.set_defaults(func=func)
        return s

    s = nuevo('listar', 'lista los autos (por defecto, los disponibles)', cmd_listar)
    g = s.add_mutually_exclusive_group()
    g.add_argument('--todos', action='store_true', help='todos los estados')
    g.add_argument('--vendidos', action='store_true', help='solo los vendidos')
    g.add_argument('--ocultos', action='store_true', help='solo los ocultos (pausados)')
    g.add_argument('--borradores', action='store_true', help='solo los borradores sin publicar')
    s.add_argument('--buscar', metavar='TEXTO', help='filtra por marca, modelo, año, color o referencia')

    s = nuevo('ver', 'muestra todos los datos de un auto', cmd_ver)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('--json', action='store_true', help='los datos tal como se guardan')

    nuevo('campos', 'lista los datos que se pueden poner a un auto', cmd_campos)

    s = nuevo('faltan', 'lo que le falta a un auto para publicarse, en el orden en que se pide', cmd_faltan)
    s.add_argument('id', metavar='<auto>')

    s = nuevo('agregar', 'empieza un auto como borrador: catalogo agregar marca=Mazda modelo=CX-30 anio=2024 …',
              cmd_agregar)
    s.add_argument('campos', nargs='+', metavar='campo=valor')
    s.add_argument('--duplicado', action='store_true', help='agregarlo aunque ya exista uno parecido')

    s = nuevo('editar', 'cambia datos: catalogo editar <auto> precio=75000000 km=30100 hp="no aplica"', cmd_editar)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('campos', nargs='+', metavar='campo=valor')

    for nombre_cmd in ('publicar', 'disponible'):
        s = nuevo(nombre_cmd, 'publica un borrador completo (o vuelve a mostrar uno oculto)', cmd_publicar)
        s.add_argument('id', metavar='<auto>')

    s = nuevo('vender', 'marca el auto como vendido (sin --confirmar solo muestra qué se va a vender)', cmd_vender)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('--fecha', metavar='AAAA-MM-DD', help='fecha de la venta (por defecto, hoy)')
    s.add_argument('--confirmar', action='store_true', help='ya se confirmó con quien lo pidió')

    s = nuevo('reactivar', 'vuelve a poner en venta un auto vendido: catalogo reactivar <auto> km=… precio=…',
              cmd_reactivar)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('campos', nargs='*', metavar='campo=valor')

    s = nuevo('ocultar', 'saca un auto publicado del sitio sin borrarlo (pausa)', cmd_ocultar)
    s.add_argument('id', metavar='<auto>')

    s = nuevo('destacar', f'lo muestra entre los {MAX_DESTACADOS} destacados del inicio (--no para quitarlo)',
              cmd_destacar)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('--no', action='store_true', help='quitarlo de los destacados')
    s.add_argument('--en-lugar-de', metavar='<auto>', help='el destacado que sale para darle el puesto')

    nuevo('destacados', 'los autos destacados en el inicio', cmd_destacados)

    s = nuevo('mover', 'cambia el orden: catalogo mover <auto> primero|ultimo|<posición>', cmd_mover)
    s.add_argument('id', metavar='<auto>')
    s.add_argument('posicion', metavar='posición')

    s = nuevo('eliminar', 'borra un auto o un borrador (para ventas usa «vender»)', cmd_eliminar)
    s.add_argument('id', metavar='<id exacto>')
    s.add_argument('--confirmar', action='store_true', help='obligatorio')

    s = nuevo('previa', 'enlace de vista previa de un borrador u oculto (sin publicarlo)', cmd_previa)
    s.add_argument('id', metavar='<auto>')

    s = nuevo('borradores', f'borradores sin publicar (se borran a los {DIAS_BORRADOR} días sin cambios)',
              cmd_borradores)
    s.add_argument('--de', metavar='ID', help='solo los de esta persona (ID de Telegram)')
    s.add_argument('--por-vencer', action='store_true', help='aviso de los que se borran mañana (si no hay, no imprime nada)')

    s = nuevo('foto', 'fotos de un auto: agregar, listar, quitar, portada, orden')
    fs = s.add_subparsers(dest='accion', metavar='acción', parser_class=Parser)
    fs.required = True
    f = nuevo('agregar', 'agrega fotos: catalogo foto agregar <auto> archivo.jpg … | --ultimas N', subgrupo=fs)
    f.set_defaults(func=cmd_foto_agregar, recibe='fotos')
    f.add_argument('id', metavar='<auto>')
    f.add_argument('archivos', nargs='*', metavar='archivo')
    f.add_argument('--ultimas', type=int, metavar='N', help='las N últimas fotos que llegaron por Telegram')
    f.add_argument('--minutos', type=int, default=120, help='con --ultimas: antigüedad máxima (por defecto 120)')
    f.add_argument('--carpeta', help='con --ultimas: carpeta donde buscar (por defecto, el caché de Hermes)')
    f.add_argument('--portada', action='store_true', help='poner las nuevas primero (la primera es la portada)')
    f.add_argument('--entrada-interna', action='store_true', help=argparse.SUPPRESS)
    f = nuevo('listar', 'lista las fotos numeradas', cmd_foto_listar, fs)
    f.add_argument('id', metavar='<auto>')
    f = nuevo('quitar', 'quita fotos por número: catalogo foto quitar <auto> 2 5', cmd_foto_quitar, fs)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('numeros', nargs='*', metavar='número')
    f.add_argument('--todas', action='store_true')
    f.add_argument('--forzar', action='store_true', help='aunque un auto publicado quede con menos del mínimo')
    f = nuevo('portada', 'usa la foto N como portada del auto', cmd_foto_portada, fs)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('numero', metavar='número')
    f = nuevo('orden', 'reordena: catalogo foto orden <auto> 3 1 2 (las no nombradas van al final)', cmd_foto_orden, fs)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('numeros', nargs='+', metavar='número')

    s = nuevo('linea', 'línea de tiempo del historial: agregar, quitar')
    ls = s.add_subparsers(dest='accion', metavar='acción', parser_class=Parser)
    ls.required = True
    f = nuevo('agregar', 'catalogo linea agregar <auto> "2024 · Mantenimiento" "Texto"', cmd_linea_agregar, ls)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('titulo', metavar='título')
    f.add_argument('texto')
    f = nuevo('quitar', 'catalogo linea quitar <auto> <número>', cmd_linea_quitar, ls)
    f.add_argument('id', metavar='<auto>')
    f.add_argument('numero', metavar='número')

    s = nuevo('portada', 'portada del inicio: ver, textos, foto, video, original', cmd_portada_ver)
    ps = s.add_subparsers(dest='accion', metavar='acción', parser_class=Parser)
    nuevo('ver', 'muestra la portada actual', cmd_portada_ver, ps)
    f = nuevo('textos', 'catalogo portada textos texto=Mazda "titulo=CX-5 | 2022" auto=<auto>', cmd_portada_textos, ps)
    f.add_argument('campos', nargs='+', metavar='campo=valor')
    for tipo in ('foto', 'video'):
        f = nuevo(tipo, f'pone {"una foto" if tipo == "foto" else "un video (hasta 60 s; se quita el audio)"} de fondo',
                  cmd_portada_medio, ps)
        f.set_defaults(recibe=tipo, tipo=tipo)
        f.add_argument('archivos', nargs='*', metavar='archivo')
        f.add_argument('--ultimo', action='store_true', help=f'{"la última foto" if tipo == "foto" else "el último video"} '
                                                            'que llegó por Telegram')
        f.add_argument('--minutos', type=int, default=120, help='con --ultimo: antigüedad máxima (por defecto 120)')
        f.add_argument('--carpeta', help=argparse.SUPPRESS)
        f.add_argument('--entrada-interna', action='store_true', help=argparse.SUPPRESS)
    f = nuevo('original', 'vuelve a la portada original del sitio', cmd_portada_original, ps)
    g = f.add_mutually_exclusive_group()
    g.add_argument('--solo-fondo', action='store_true')
    g.add_argument('--solo-textos', action='store_true')

    s = nuevo('servicios', 'videos de YouTube de «Otros servicios»: ver, video', cmd_servicios_ver)
    ss = s.add_subparsers(dest='accion', metavar='acción', parser_class=Parser)
    nuevo('ver', 'muestra los videos de cada servicio', cmd_servicios_ver, ss)
    f = nuevo('video', 'catalogo servicios video posventa|transito|fotografia|acompanamiento <enlace|borrar>',
              cmd_servicios_video, ss)
    f.add_argument('servicio')
    f.add_argument('enlace')

    s = nuevo('resumen', 'resumen corto: vendidos, publicados, autos incompletos', cmd_resumen)
    s.add_argument('--dias', type=int, default=7, help='periodo en días (por defecto 7)')

    s = nuevo('informe', 'informe de movimiento: la semana que terminó ayer, o --mes (el mes anterior)', cmd_informe)
    g = s.add_mutually_exclusive_group()
    g.add_argument('--mes', action='store_true', help='el mes anterior completo')
    g.add_argument('--desde', metavar='AAAA-MM-DD')
    s.add_argument('--hasta', metavar='AAAA-MM-DD')

    s = nuevo('precios', 'historial de precios de un auto', cmd_precios)
    s.add_argument('id', metavar='<auto>')

    s = nuevo('historial', 'últimos cambios del catálogo', cmd_historial)
    s.add_argument('-n', type=int, default=15, help='cuántos (por defecto 15)')

    s = nuevo('deshacer', 'deshace tu último cambio (repetir para ir más atrás)', cmd_deshacer)
    s.add_argument('--forzar', action='store_true', help='aunque haya cambios posteriores en el mismo auto')

    nuevo('validar', 'revisa el catálogo, las fotos y la portada', cmd_validar)

    s = nuevo('limpiar', 'borra fotos y videos que nadie usa hace más de N días (administrador)', cmd_limpiar)
    s.add_argument('--dias', type=int, default=30)

    s = nuevo('respaldar', 'guarda una copia comprimida del catálogo (administrador)', cmd_respaldar)
    s.add_argument('--destino', help=f'carpeta (por defecto {RESPALDOS})')
    s.add_argument('--conservar', type=int, default=14, help='cuántas copias guardar (por defecto 14)')

    s = nuevo('mantenimiento', 'validar + borradores vencidos + limpiar + respaldar; lo corre el servidor cada día',
              cmd_mantenimiento)
    s.set_defaults(dias=30, destino=None, conservar=14)

    s = nuevo('iniciar', 'crea el catálogo si no existe (administrador)', cmd_iniciar)
    s.add_argument('--desde', metavar='ARCHIVO', help='inventario.js o .json con los autos iniciales')

    s = nuevo('importar', 'reemplaza todo el catálogo con un archivo (administrador)', cmd_importar)
    s.add_argument('archivo')
    s.add_argument('--confirmar', action='store_true', help='obligatorio')

    nuevo('migrar', 'pone al día los datos con esta versión (lo corre mendiautos.sh al publicar)', cmd_migrar)
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
    POR_SUDO[0] = os.geteuid() != 0 and os.environ.get('SUDO_USER', 'root') != 'root'
    try:
        if args.comando in SOLO_ADMIN and POR_SUDO[0]:
            raise Fallo('Este comando es solo para el administrador del servidor.')
        identificar(args.por)
        entradas, argv_interno = None, argv
        recibe = getattr(args, 'recibe', None)
        if recibe:
            if args.entrada_interna:
                entradas = desempaquetar(sys.stdin.buffer, MAX_BYTES_VIDEO if recibe == 'video' else MAX_BYTES_FOTO)
            else:
                rutas = args.archivos
                if recibe == 'fotos' and args.ultimas:
                    if rutas:
                        raise Fallo('Usa archivos o --ultimas, no ambos.')
                    if not 1 <= args.ultimas <= MAX_ARCHIVOS:
                        raise Fallo(f'--ultimas va de 1 a {MAX_ARCHIVOS}.')
                    rutas = fotos_recientes(args.ultimas, args.minutos, args.carpeta)
                elif recibe in ('foto', 'video') and args.ultimo:
                    if rutas:
                        raise Fallo('Usa un archivo o --ultimo, no ambos.')
                    rutas = fotos_recientes(1, args.minutos, args.carpeta) if recibe == 'foto' else \
                        videos_recientes(args.minutos, args.carpeta)
                if recibe in ('foto', 'video') and len(rutas) > 1:
                    raise Fallo('La portada lleva un solo archivo.')
                entradas = leer_archivos(rutas, MAX_BYTES_VIDEO if recibe == 'video' else MAX_BYTES_FOTO,
                                         'foto' if recibe != 'video' else 'video')
                extra = (['--nota', args.nota] if args.nota else []) + (['--por', args.por] if args.por else [])
                if recibe == 'fotos':
                    argv_interno = ['foto', 'agregar', args.id, '--entrada-interna'] + \
                        (['--portada'] if args.portada else []) + extra
                else:
                    argv_interno = ['portada', recibe, '--entrada-interna'] + extra
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
