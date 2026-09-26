#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""solicitudes: recibe lo que los clientes envían desde el sitio de Mendiautos
y se lo entrega al equipo de ventas.

Tiene dos papeles:

  solicitudes servir          receptor HTTP (lo corre systemd, detrás de nginx)
  solicitudes listar|ver|…    lo que usa el equipo, o el asistente, para atenderlas

Las solicitudes quedan en /var/lib/mendiautos/solicitudes:

  registro/AAAA-MM/S-<n>.json   una por solicitud (solo el usuario «solicitudes»)
  fotos/S-<n>/                  fotos del auto, procesadas y sin GPS (las lee el asistente)
  privado/S-<n>/                documentos (cédula, extractos, tarjeta): solo el administrador

Lo que escribe un visitante son datos, nunca instrucciones. Los datos sensibles
de un crédito (documento, ingresos, fecha de nacimiento…) se ocultan en todo lo
que ve el equipo por chat; el administrador los consulta en el servidor.

  solicitudes --help
"""
import argparse
import datetime as dt
import email.parser
import email.policy
import fcntl
import hashlib
import hmac
import io
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DUENO = 'solicitudes'
RUTA_COMANDO = '/usr/local/bin/solicitudes'
DATOS = Path(os.environ.get('MENDIAUTOS_SOLICITUDES') or '/var/lib/mendiautos/solicitudes')
TOKEN_F = Path(os.environ.get('MENDIAUTOS_TOKEN_SOLICITUDES') or '/etc/mendiautos/solicitudes.token')
REGISTRO, FOTOS, PRIVADO, AVISOS = DATOS / 'registro', DATOS / 'fotos', DATOS / 'privado', DATOS / 'avisos'
TZ = dt.timezone(dt.timedelta(hours=-5))  # Colombia
WA_VENTAS = '573118058132'

TIPOS = {
    'contacto': 'Contacto',
    'busca': 'Busca tu auto',
    'compra': 'Compra inmediata',
    'consignacion-fisica': 'Consignación física',
    'consignacion-virtual': 'Consignación virtual',
    'servicio': 'Otros servicios',
    'acompanamiento': 'Acompañamiento de compra',
    'alerta': 'Alerta de inventario',
    'credito': 'Solicitud de crédito',
    'whatsapp': 'WhatsApp (asistente de clientes)',
    'prueba': 'Prueba del sistema',
}
# Cómo se le recuerda al cliente por qué le escribimos (enlace de WhatsApp).
MOTIVO = {
    'contacto': 'por tu mensaje en nuestra página', 'busca': 'por el auto que estás buscando',
    'compra': 'por la oferta para tu auto', 'consignacion-fisica': 'por la consignación de tu auto',
    'consignacion-virtual': 'por la publicación de tu auto', 'servicio': 'por el servicio que nos pediste',
    'acompanamiento': 'por el acompañamiento de compra que nos pediste', 'alerta': 'por tu alerta de inventario',
    'credito': 'por tu solicitud de crédito', 'whatsapp': 'por tu consulta en nuestro WhatsApp', 'prueba': '(prueba)',
}
ESTADOS = ('nueva', 'en-curso', 'atendida', 'descartada')
PENDIENTES = ('nueva', 'en-curso')

MAX_CUERPO = 45 * 1024 * 1024
MAX_FOTOS, MAX_BYTES_FOTO = 12, 15 * 1024 * 1024
MAX_DOCS, MAX_BYTES_DOC = 8, 12 * 1024 * 1024
MAX_CAMPOS, LARGO_CAMPO, LARGO_TEXTO = 60, 300, 3000
LIMITE_POR_IP, LIMITE_GLOBAL = 20, 300         # solicitudes por hora (muchos celulares comparten IP)
TIEMPO_MINIMO_MS = 2500                        # un humano tarda más en llenar un formulario

# Etiquetas cuyo valor no se muestra por chat (van al modelo de IA y a Telegram/WhatsApp).
SENSIBLE = re.compile(r'documento|c[eé]dula|pasaporte|nacimiento|ingreso|egreso|salario|deuda|'
                      r'centrales|patrimonio|cuenta bancaria', re.I)
ES_NOMBRE = re.compile(r'^nombre', re.I)
ES_CELULAR = re.compile(r'celular|tel[eé]fono|whatsapp', re.I)
ES_CORREO = re.compile(r'correo|e-?mail', re.I)
ES_TEXTO_LARGO = re.compile(r'mensaje|observacion|cu[eé]ntanos|qu[eé] tienes en mente|necesitas|palabras|estado general|'
                            r'espec[ií]fico', re.I)
CONTROL = re.compile('[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]')


class Fallo(Exception):
    """Error que se le muestra tal cual a quien usa el comando."""


class Rechazo(Exception):
    """Solicitud web inválida: se responde al navegador con este mensaje."""

    def __init__(self, mensaje, codigo=400):
        super().__init__(mensaje)
        self.codigo = codigo


# -------------------------------------------------------------------- textos
def ahora():
    return dt.datetime.now(TZ)


def texto(v, largo):
    s = CONTROL.sub('', str(v).replace('\r\n', '\n').replace('\r', '\n'))
    # «MEDIA:<ruta>» en un mensaje haría que el chat adjunte ese archivo: se desarma.
    s = re.sub(r'\b(media)\s*:', r'\1 :', s, flags=re.I)
    s = '\n'.join(re.sub(r'[ \t]+', ' ', l).strip() for l in s.split('\n'))
    s = re.sub(r'\n{3,}', '\n\n', s).strip()
    return s[:largo]


def etiqueta(v):
    s = re.sub(r'\(opcional\)|\*', '', texto(v, 80), flags=re.I)
    return re.sub(r'\s+', ' ', s).strip(' :') or 'Campo'


def sin_acentos(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s)) if not unicodedata.combining(c)).lower()


def celular(v):
    """'+57 300 123 4567' -> '573001234567' (vacío si no parece un número)."""
    d = re.sub(r'\D', '', str(v or ''))
    if len(d) == 10 and d.startswith('3'):
        d = '57' + d
    return d if 10 <= len(d) <= 15 else ''


def correo(v):
    s = texto(v, 120).lower()
    return s if re.fullmatch(r'[^@\s]+@[^@\s]+\.[a-z]{2,}', s) else ''


def celular_legible(d):
    if len(d) == 12 and d.startswith('57'):
        return f'{d[2:5]} {d[5:8]} {d[8:]}'
    return '+' + d if d else ''


def hace(fecha_iso):
    try:
        t = dt.datetime.fromisoformat(fecha_iso)
    except (TypeError, ValueError):
        return ''
    s = (ahora() - t).total_seconds()
    if s < 60:
        return 'hace un momento'
    if s < 3600:
        return f'hace {max(1, int(s // 60))} min'
    if s < 86400:
        return f'hace {int(s // 3600)} h'
    d = int(s // 86400)
    return 'ayer' if d == 1 else f'hace {d} días'


def plural(n, uno, varios):
    return f'{n} {uno if n == 1 else varios}'


# ------------------------------------------------------------ almacenamiento
def escribir_atomico(ruta, contenido, modo=0o600):
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


class Candado:
    def __enter__(self):
        DATOS.mkdir(parents=True, exist_ok=True)
        self.f = open(DATOS / '.candado', 'a')
        fin = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() > fin:
                    self.f.close()
                    raise Fallo('Las solicitudes están ocupadas con otro cambio; intenta de nuevo.')
                time.sleep(0.1)

    def __exit__(self, *exc):
        self.f.close()


def preparar_carpetas():
    for d, modo in ((DATOS, 0o750), (REGISTRO, 0o700), (FOTOS, 0o750), (PRIVADO, 0o700), (AVISOS, 0o700)):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, modo)


def siguiente_id():
    f = DATOS / 'secuencia'
    try:
        n = int(f.read_text().strip()) + 1
    except (OSError, ValueError):
        n = 1001
    escribir_atomico(f, f'{n}\n'.encode())
    return f'S-{n}'


def ruta_solicitud(id_s):
    if not re.fullmatch(r'S-\d{1,9}', id_s or ''):
        return None
    hallados = sorted(REGISTRO.glob(f'*/{id_s}.json'))
    return hallados[0] if hallados else None


def cargar(id_s):
    id_s = normalizar_id(id_s)
    r = ruta_solicitud(id_s)
    if not r:
        raise Fallo(f'No existe la solicitud {id_s}. Consulta: solicitudes listar --todas')
    return r, json.loads(r.read_text('utf-8'))


def normalizar_id(v):
    d = re.sub(r'\D', '', str(v or ''))
    return f'S-{int(d)}' if d else str(v or '')


def guardar(ruta, s):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    escribir_atomico(ruta, (json.dumps(s, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def todas():
    res = []
    for r in sorted(REGISTRO.glob('*/S-*.json')):
        try:
            res.append(json.loads(r.read_text('utf-8')))
        except (OSError, ValueError):
            continue
    res.sort(key=lambda s: int(s['id'][2:]))
    return res


# ------------------------------------------------------------------ archivos
def es_imagen(b):
    return b[:3] == b'\xff\xd8\xff' or b[:8] == b'\x89PNG\r\n\x1a\n' or (b[:4] == b'RIFF' and b[8:12] == b'WEBP') \
        or (b[4:8] == b'ftyp' and b[8:12] in (b'heic', b'heix', b'mif1', b'msf1', b'hevc'))


def extension_documento(b):
    if b[:5] == b'%PDF-':
        return 'pdf'
    if b[:3] == b'\xff\xd8\xff':
        return 'jpg'
    if b[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if b[:4] == b'RIFF' and b[8:12] == b'WEBP':
        return 'webp'
    if b[4:8] == b'ftyp' and b[8:12] in (b'heic', b'heix', b'mif1', b'msf1', b'hevc'):
        return 'heic'
    return ''


def procesar_foto(contenido):
    """Re-codifica la foto (sin EXIF ni GPS, máx. 1600 px). Devuelve bytes JPEG o None si no se puede."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return contenido if contenido[:3] == b'\xff\xd8\xff' else None
    Image.MAX_IMAGE_PIXELS = 60_000_000
    try:
        im = Image.open(io.BytesIO(contenido))
        if im.format in ('JPEG', 'MPO'):
            im.draft('RGB', (3200, 3200))
        im.load()
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        if im.mode in ('RGBA', 'LA', 'PA') or (im.mode == 'P' and 'transparency' in im.info):
            rgba = im.convert('RGBA')
            fondo = Image.new('RGB', im.size, (255, 255, 255))
            fondo.paste(rgba, mask=rgba.split()[-1])
            im = fondo
        else:
            im = im.convert('RGB')
        im.thumbnail((1600, 1600), getattr(Image, 'Resampling', Image).LANCZOS)
        salida = io.BytesIO()
        im.save(salida, 'JPEG', quality=82, optimize=True, progressive=True)
        return salida.getvalue()
    except Exception:
        return None


# ----------------------------------------------------------------- creación
def crear(tipo, pares, contacto_extra=None, archivos=(), meta=None, origen='web'):
    """Valida y guarda una solicitud. `pares` = [(etiqueta, valor)], `archivos` = [(clase, etiqueta, nombre, bytes)]."""
    if tipo not in TIPOS:
        raise Rechazo('Tipo de solicitud desconocido.')
    datos, contacto = [], {'nombre': '', 'celular': '', 'correo': ''}
    for par in list(pares)[:MAX_CAMPOS]:
        if not (isinstance(par, (list, tuple)) and len(par) == 2):
            continue
        k = etiqueta(par[0])
        largo = LARGO_TEXTO if ES_TEXTO_LARGO.search(k) else LARGO_CAMPO
        v = texto(par[1], largo)
        if not v:
            continue
        if ES_NOMBRE.search(k) and not contacto['nombre']:
            contacto['nombre'] = texto(v, 80)
            continue
        if ES_CELULAR.search(k) and not contacto['celular'] and celular(v):
            contacto['celular'] = celular(v)
            continue
        if ES_CORREO.search(k) and not contacto['correo'] and correo(v):
            contacto['correo'] = correo(v)
            continue
        datos.append([k, v])
    for k, v in (contacto_extra or {}).items():
        if k == 'celular':
            v = celular(v)
        elif k == 'correo':
            v = correo(v)
        else:
            v = texto(v, 80)
        if v and not contacto.get(k):
            contacto[k] = v
    if tipo not in ('prueba',) and not (contacto['celular'] or contacto['correo']):
        raise Rechazo('Déjanos un celular o un correo para poder contactarte.')
    fotos = [a for a in archivos if a[0] == 'foto']
    docs = [a for a in archivos if a[0] != 'foto']
    if len(fotos) > MAX_FOTOS:
        raise Rechazo(f'Puedes enviar hasta {MAX_FOTOS} fotos.')
    if len(docs) > MAX_DOCS:
        raise Rechazo(f'Puedes enviar hasta {MAX_DOCS} documentos.')
    for clase, _, nombre, b in archivos:
        limite = MAX_BYTES_FOTO if clase == 'foto' else MAX_BYTES_DOC
        if len(b) > limite:
            raise Rechazo(f'El archivo «{texto(nombre, 60)}» pesa más de {limite // 1048576} MB.')
    procesadas, avisos = [], []
    for clase, campo, nombre, b in archivos:
        if clase == 'foto':
            jpg = procesar_foto(b) if es_imagen(b) else None
            if jpg is None:
                avisos.append(f'La foto «{texto(nombre, 60)}» no se pudo leer.')
                continue
            procesadas.append(('foto', etiqueta(campo), jpg, 'jpg'))
        else:
            ext = extension_documento(b)
            if not ext:
                avisos.append(f'«{texto(nombre, 60)}» no es PDF ni imagen; no se guardó.')
                continue
            procesadas.append(('documento', etiqueta(campo), b, ext))
    with Candado():
        preparar_carpetas()
        id_s = siguiente_id()
        guardados = []
        for n, (clase, campo, b, ext) in enumerate(procesadas, 1):
            base = PRIVADO if clase == 'documento' else FOTOS
            carpeta = base / id_s
            carpeta.mkdir(exist_ok=True)
            os.chmod(carpeta, 0o700 if clase == 'documento' else 0o750)
            nombre_f = f'{n}-{hashlib.sha256(b).hexdigest()[:12]}.{ext}'
            escribir_atomico(carpeta / nombre_f, b, 0o600 if clase == 'documento' else 0o640)
            guardados.append({'clase': clase, 'campo': campo, 'archivo': nombre_f, 'bytes': len(b)})
        momento = ahora()
        s = {
            'id': id_s, 'tipo': tipo, 'origen': origen, 'estado': 'nueva',
            'recibida': momento.isoformat(timespec='seconds'),
            'pagina': texto((meta or {}).get('pagina', ''), 80),
            'contacto': contacto, 'datos': datos, 'archivos': guardados,
            'consentimiento': bool((meta or {}).get('consentimiento')) if (meta or {}).get('consentimiento') is not None else None,
            'avisos_archivos': avisos, 'avisada': {}, 'historial': [],
        }
        guardar(REGISTRO / momento.strftime('%Y-%m') / f'{id_s}.json', s)
    return s


# ------------------------------------------------------------------ vistas
def visible(k, v, completo=False):
    if not completo and SENSIBLE.search(k):
        return '(privado)'
    if re.search(r'precio|presupuesto|monto|valor', k, re.I) and re.fullmatch(r'\$?\s*\d{5,}', v.replace('.', '')):
        return '$' + f'{int(re.sub(r"[^0-9]", "", v)):,}'.replace(',', '.')
    return v


def enlace_whatsapp(s):
    c = s['contacto']
    if not c.get('celular'):
        return ''
    nombre = (c.get('nombre') or '').split(' ')[0]
    msg = re.sub(r'\s+', ' ', f'Hola {nombre}, te escribimos de Mendiautos {MOTIVO.get(s["tipo"], "por tu solicitud")}.')
    return f'https://wa.me/{c["celular"]}?text=' + urllib.parse.quote(msg)


def resumen_corto(s):
    """Una línea con lo más importante (para listas)."""
    d = dict(s['datos'])
    claves = [k for k in d if not SENSIBLE.search(k) and not ES_TEXTO_LARGO.search(k)]
    auto = ' '.join(d[k] for k in claves if re.match(r'marca|modelo|a[nñ]o$|servicio|tipo de cr|auto de interes', sin_acentos(k)))
    otro = next((d[k] for k in d if ES_TEXTO_LARGO.search(k)), '')
    base = auto or ', '.join(f'{k}: {d[k]}' for k in claves[:2])
    if otro:
        base = (base + ' · ' if base else '') + '«' + (otro[:60] + ('…' if len(otro) > 60 else '')) + '»'
    return base[:140]


def linea(s):
    c = s['contacto']
    quien = c.get('nombre') or 'Sin nombre'
    tel = celular_legible(c.get('celular', '')) or c.get('correo', '')
    estado = '' if s['estado'] == 'nueva' else f' [{s["estado"]}]'
    r = resumen_corto(s)
    return f'{s["id"]:<7} {hace(s["recibida"]):<12} {TIPOS.get(s["tipo"], s["tipo"])} · {quien} · {tel}' + \
        (f' · {r}' if r else '') + estado


def texto_aviso(s, con_fotos=True):
    """Mensaje para el canal de ventas."""
    c = s['contacto']
    partes = [f'🆕 {s["id"]} · {TIPOS.get(s["tipo"], s["tipo"])}']
    quien = ' · '.join(x for x in (c.get('nombre'), celular_legible(c.get('celular', '')), c.get('correo')) if x)
    if quien:
        partes.append(quien)
    campos = [(k, visible(k, v)) for k, v in s['datos'] if not ES_TEXTO_LARGO.search(k) and not SENSIBLE.search(k)]
    if campos:
        partes.append(' · '.join(f'{k}: {v}' for k, v in campos[:16]) + (' · …' if len(campos) > 16 else ''))
    for k, v in s['datos']:
        if ES_TEXTO_LARGO.search(k):
            partes.append(f'«{v[:400]}{"…" if len(v) > 400 else ""}»')
    privados = [k for k, _ in s['datos'] if SENSIBLE.search(k)]
    if privados:
        partes.append('Privado (solo en el servidor): ' + ', '.join(privados))
    fotos = [a for a in s['archivos'] if a['clase'] == 'foto']
    docs = [a for a in s['archivos'] if a['clase'] != 'foto']
    if fotos or docs:
        partes.append(' · '.join(x for x in (
            plural(len(fotos), 'foto', 'fotos') if fotos else '',
            plural(len(docs), 'documento privado', 'documentos privados') if docs else '') if x))
    wa = enlace_whatsapp(s)
    if wa:
        partes.append(f'Escribirle: {wa}')
    partes.append(f'Cuando la atiendas, dime «atendí la {s["id"]}».')
    if con_fotos:
        for a in fotos[:4]:
            partes.append(f'MEDIA:{FOTOS / s["id"] / a["archivo"]}')
    return '\n'.join(partes)


# ------------------------------------------------------------------ comandos
def cmd_listar(a):
    lista = todas()
    if not a.todas:
        lista = [s for s in lista if s['estado'] in ((a.estado,) if a.estado else PENDIENTES)]
    if a.tipo:
        lista = [s for s in lista if s['tipo'] == a.tipo]
    if a.buscar:
        q = sin_acentos(a.buscar)
        lista = [s for s in lista if q in sin_acentos(json.dumps(s, ensure_ascii=False))]
    total, lista = len(lista), lista[::-1][:max(1, a.n)]
    que = 'en total' if a.todas else (a.estado or 'pendientes')
    print(f'{plural(total, "solicitud", "solicitudes")} {que}' +
          ((' (la más reciente):' if len(lista) == 1 else f' (las {len(lista)} más recientes):')
           if total > len(lista) else ':' if lista else '.'))
    for s in lista:
        print('  ' + linea(s))
    if not a.todas and not lista:
        print('No hay nada pendiente. 👍')


def cmd_ver(a):
    if a.completo and not es_admin():
        raise Fallo('Los datos completos y los documentos solo los ve el administrador en el servidor.')
    _, s = cargar(a.id)
    c = s['contacto']
    print(f'{s["id"]} · {TIPOS.get(s["tipo"], s["tipo"])} · recibida {s["recibida"][:16].replace("T", " ")} ({hace(s["recibida"])})')
    print(f'Estado: {s["estado"]}' + (f' · desde la página {s["pagina"]}' if s.get('pagina') else '') +
          ('' if s.get('consentimiento') is None else
           ' · autorizó el tratamiento de datos' if s['consentimiento'] else ' · NO marcó la autorización de datos'))
    print(f'Contacto: {c.get("nombre") or "sin nombre"} · {celular_legible(c.get("celular", "")) or "sin celular"} · '
          f'{c.get("correo") or "sin correo"}')
    for k, v in s['datos']:
        v = visible(k, v, a.completo)
        print(f'  {k}: {v}' if '\n' not in v else f'  {k}:\n    ' + v.replace('\n', '\n    '))
    fotos = [x for x in s['archivos'] if x['clase'] == 'foto']
    docs = [x for x in s['archivos'] if x['clase'] != 'foto']
    if fotos:
        print(f'Fotos ({len(fotos)}):')
        for x in fotos:
            print(f'  {FOTOS / s["id"] / x["archivo"]}')
    if docs:
        if a.completo:
            print(f'Documentos ({len(docs)}):')
            for x in docs:
                print(f'  {x["campo"]}: {PRIVADO / s["id"] / x["archivo"]}')
        else:
            print(f'Documentos: {len(docs)} (privados; los descarga el administrador en el servidor)')
    for x in s.get('avisos_archivos') or []:
        print(f'Aviso: {x}')
    wa = enlace_whatsapp(s)
    if wa:
        print(f'Escribirle por WhatsApp: {wa}')
    if s['historial']:
        print('Historial:')
        for h in s['historial']:
            print(f'  {h["fecha"][:16].replace("T", " ")} · {h["accion"]}' + (f' · {h["nota"]}' if h.get('nota') else '') +
                  (f' ({h["por"]})' if h.get('por') else ''))


def registrar(id_s, accion, nota='', estado=None):
    with Candado():
        r, s = cargar(id_s)
        if estado:
            s['estado'] = estado
        s['historial'].append({'fecha': ahora().isoformat(timespec='seconds'), 'accion': accion,
                               'nota': texto(nota, 500) if nota else '', 'por': quien_llama()})
        guardar(r, s)
    return s


def cmd_atender(a):
    s = registrar(a.id, 'atendida', a.nota, 'atendida')
    print(f'Listo: {s["id"]} ({TIPOS.get(s["tipo"], s["tipo"])} de {s["contacto"].get("nombre") or "sin nombre"}) quedó atendida.')


def cmd_estado(a):
    if a.estado not in ESTADOS:
        raise Fallo('El estado debe ser: ' + ', '.join(ESTADOS))
    s = registrar(a.id, f'estado: {a.estado}', a.nota, a.estado)
    print(f'{s["id"]} ahora está «{a.estado}».')


def cmd_nota(a):
    s = registrar(a.id, 'nota', a.texto)
    print(f'Nota guardada en {s["id"]}.')


def cmd_avisar(a):
    """Para las tareas programadas de Hermes: imprime lo nuevo para un canal (vacío = nada nuevo).

    Con --reintentar (el chat no recibió el aviso anterior) vuelve a incluir la
    última tanda, salvo las que el equipo ya tomó."""
    canal = re.sub(r'[^a-z0-9_-]', '', a.canal.lower())[:20]
    if not canal:
        raise Fallo('Indica el canal, por ejemplo: --canal telegram')
    with Candado():
        preparar_carpetas()
        estado_f = AVISOS / f'{canal}.json'
        try:
            estado = json.loads(estado_f.read_text())
            desde = estado['desde']
        except (OSError, ValueError, KeyError, TypeError):
            # Canal nuevo: solo avisa lo de las últimas 24 horas, no todo el archivo.
            estado = {'desde': (ahora() - dt.timedelta(days=1)).isoformat(timespec='seconds')}
            desde = estado['desde']
            escribir_atomico(estado_f, json.dumps(estado).encode())
        if a.reintentar:
            for id_s in estado.get('ultima') or []:
                r = ruta_solicitud(id_s)
                if not r:
                    continue
                s = json.loads(r.read_text('utf-8'))
                if s['estado'] == 'nueva' and canal in (s.get('avisada') or {}):
                    del s['avisada'][canal]
                    guardar(r, s)
        sin_aviso = [s for s in todas() if canal not in (s.get('avisada') or {}) and s['recibida'] >= desde]
        # Las que el equipo ya tomó (por otro canal) no se repiten: se marcan en silencio.
        nuevas = [s for s in sin_aviso if s['estado'] == 'nueva']
        tanda = nuevas[:max(1, a.max)]
        for s in tanda + [x for x in sin_aviso if x['estado'] != 'nueva']:
            r = ruta_solicitud(s['id'])
            s.setdefault('avisada', {})[canal] = ahora().isoformat(timespec='seconds')
            guardar(r, s)
        if tanda:
            estado['ultima'] = [s['id'] for s in tanda]
            escribir_atomico(estado_f, json.dumps(estado).encode())
    if not tanda:
        return
    bloques = [texto_aviso(s, con_fotos=len(tanda) == 1) for s in tanda]
    if len(tanda) > 1 and any(x['clase'] == 'foto' for s in tanda for x in s['archivos']):
        bloques.append('Para ver las fotos de una, pídemelo: «muéstrame las fotos de la S-…».')
    if len(nuevas) > len(tanda):
        bloques.append(f'…y {len(nuevas) - len(tanda)} más en el próximo aviso (o «solicitudes pendientes»).')
    print('\n\n'.join(bloques))


def cmd_resumen(a):
    lista = todas()
    desde = (ahora() - dt.timedelta(days=a.dias)).isoformat(timespec='seconds')
    recientes = [s for s in lista if s['recibida'] >= desde and s['tipo'] != 'prueba']
    pendientes = [s for s in lista if s['estado'] in PENDIENTES and s['tipo'] != 'prueba']
    viejas = [s for s in pendientes if (ahora() - dt.datetime.fromisoformat(s['recibida'])).total_seconds() > 86400]
    if a.silencioso_si_vacio and not recientes and not pendientes:
        return
    por_tipo = {}
    for s in recientes:
        por_tipo[s['tipo']] = por_tipo.get(s['tipo'], 0) + 1
    print(f'Ventas · solicitudes de {"hoy" if a.dias == 1 else f"los últimos {a.dias} días"}: {len(recientes)}' +
          (' (' + ', '.join(f'{TIPOS[t].lower()} {n}' for t, n in sorted(por_tipo.items(), key=lambda x: -x[1])) + ')'
           if por_tipo else ''))
    print(f'Pendientes por atender: {len(pendientes)}' + (f' · {len(viejas)} llevan más de un día ⚠️' if viejas else ''))
    for s in pendientes[:12]:
        print('  ' + linea(s))
    if len(pendientes) > 12:
        print(f'  … y {len(pendientes) - 12} más (solicitudes listar)')


def cmd_probar(a):
    s = crear('prueba', [['Mensaje', 'Solicitud de prueba para revisar que los avisos lleguen al canal de ventas.']],
              {'nombre': 'Prueba del sistema'}, meta={'pagina': 'solicitudes probar'}, origen='prueba')
    print(f'Creé la solicitud de prueba {s["id"]}. En menos de un minuto debería llegar el aviso al canal de ventas.')


def cmd_documentos(a):
    if not es_admin():
        raise Fallo('Solo el administrador puede sacar documentos privados.')
    _, s = cargar(a.id)
    docs = [x for x in s['archivos'] if x['clase'] != 'foto']
    if not docs:
        print(f'{s["id"]} no tiene documentos.')
        return
    destino = Path(a.destino)
    destino.mkdir(parents=True, exist_ok=True)
    for x in docs:
        nombre = re.sub(r'[^A-Za-z0-9._-]+', '_', f'{s["id"]}-{x["campo"]}-{x["archivo"]}')
        shutil.copyfile(PRIVADO / s['id'] / x['archivo'], destino / nombre)
        print(f'  {destino / nombre}')


def cmd_limpiar(a):
    """Retención: borra documentos y solicitudes viejas (lo corre el mantenimiento diario)."""
    limite_docs = ahora() - dt.timedelta(days=a.dias_documentos)
    limite_sol = ahora() - dt.timedelta(days=a.dias_solicitudes)
    docs = sols = 0
    with Candado():
        for r in sorted(REGISTRO.glob('*/S-*.json')):
            try:
                s = json.loads(r.read_text('utf-8'))
                recibida = dt.datetime.fromisoformat(s['recibida'])
            except (OSError, ValueError, KeyError):
                continue
            if recibida < limite_sol:
                shutil.rmtree(FOTOS / s['id'], ignore_errors=True)
                shutil.rmtree(PRIVADO / s['id'], ignore_errors=True)
                r.unlink()
                sols += 1
            elif recibida < limite_docs and (PRIVADO / s['id']).exists():
                shutil.rmtree(PRIVADO / s['id'], ignore_errors=True)
                s['archivos'] = [x for x in s['archivos'] if x['clase'] == 'foto']
                s['historial'].append({'fecha': ahora().isoformat(timespec='seconds'), 'accion':
                                       f'documentos borrados por retención ({a.dias_documentos} días)', 'por': 'sistema'})
                guardar(r, s)
                docs += 1
    print(f'Retención: {plural(sols, "solicitud borrada", "solicitudes borradas")} (más de {a.dias_solicitudes} días), '
          f'documentos borrados de {plural(docs, "solicitud", "solicitudes")} (más de {a.dias_documentos} días).')


# ------------------------------------------------------------------ servidor
class Limitador:
    def __init__(self):
        self.lock, self.por_ip, self.global_ = threading.Lock(), {}, []

    def permitir(self, ip):
        t = time.time()
        with self.lock:
            self.global_ = [x for x in self.global_ if t - x < 3600]
            lista = [x for x in self.por_ip.get(ip, []) if t - x < 3600]
            if len(lista) >= LIMITE_POR_IP or len(self.global_) >= LIMITE_GLOBAL:
                return False
            lista.append(t)
            self.por_ip[ip] = lista
            self.global_.append(t)
            if len(self.por_ip) > 5000:
                self.por_ip = {k: v for k, v in self.por_ip.items() if v and t - v[-1] < 3600}
            return True


LIMITADOR = Limitador()


def leer_token():
    try:
        return TOKEN_F.read_text().strip()
    except OSError:
        return ''


class Receptor(BaseHTTPRequestHandler):
    server_version = 'Mendiautos'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):  # sin datos personales en el registro
        sys.stderr.write('%s %s\n' % (self.command, fmt % args if args else fmt))

    def responder(self, codigo, obj):
        self.close_connection = True  # una petición por conexión (nginx no reutiliza)
        b = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.split('?')[0] == '/api/salud':
            return self.responder(200, {'ok': True})
        self.responder(404, {'ok': False, 'error': 'No encontrado.'})

    def do_POST(self):
        ruta = self.path.split('?')[0]
        try:
            largo = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            largo = -1
        try:
            if largo <= 0 or largo > MAX_CUERPO:
                raise Rechazo('El envío está vacío o es demasiado grande (máximo 45 MB).', 413)
            if ruta == '/api/solicitud':
                ip = (self.headers.get('X-Real-IP') or self.client_address[0])[:64]
                if not LIMITADOR.permitir(ip):
                    raise Rechazo('Recibimos muchos envíos seguidos. Intenta en un rato o escríbenos por WhatsApp.', 429)
                s = self.solicitud_web(largo)
            elif ruta == '/interno/solicitud' and self.client_address[0] in ('127.0.0.1', '::1'):
                s = self.solicitud_interna(largo)
            else:
                raise Rechazo('No encontrado.', 404)
            print(f'solicitud {s["id"]} recibida ({s["tipo"]}, {len(s["archivos"])} archivos)', file=sys.stderr)
            self.responder(200, {'ok': True, 'id': s['id'], 'avisos': s.get('avisos_archivos') or []})
        except Rechazo as e:
            self.responder(e.codigo, {'ok': False, 'error': str(e)})
        except Exception as e:  # nunca mostrar detalles internos al visitante
            print(f'error interno: {e.__class__.__name__}: {e}', file=sys.stderr)
            self.responder(500, {'ok': False, 'error': 'No pudimos guardar tu solicitud. Escríbenos por WhatsApp.'})

    def solicitud_web(self, largo):
        ctype = self.headers.get('Content-Type', '')
        if not ctype.startswith('multipart/form-data'):
            raise Rechazo('Formato de envío no válido.')
        cuerpo = self.rfile.read(largo)
        msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            b'Content-Type: ' + ctype.encode('latin-1') + b'\r\nMIME-Version: 1.0\r\n\r\n' + cuerpo)
        if not msg.is_multipart():
            raise Rechazo('Formato de envío no válido.')
        meta, pares, archivos = {}, [], []
        for parte in msg.iter_parts():
            nombre = parte.get_param('name', header='content-disposition') or ''
            contenido = parte.get_payload(decode=True) or b''
            if nombre in ('meta', 'campos'):
                try:
                    valor = json.loads(contenido.decode('utf-8', 'replace') or ('{}' if nombre == 'meta' else '[]'))
                except ValueError:
                    raise Rechazo('Formato de envío no válido.')
                if nombre == 'meta':
                    meta = valor
                else:
                    pares = valor
            elif ':' in nombre and parte.get_filename() is not None:
                clase, campo = nombre.split(':', 1)
                if contenido:
                    archivos.append(('foto' if clase == 'foto' else 'documento', campo, parte.get_filename(), contenido))
        if not isinstance(meta, dict) or not isinstance(pares, list):
            raise Rechazo('Formato de envío no válido.')
        if meta.get('hp'):  # campo trampa: lo llenan los robots
            raise Rechazo('Envío rechazado.', 400)
        try:
            if int(meta.get('t') or 0) < TIEMPO_MINIMO_MS:
                raise Rechazo('El formulario se envió demasiado rápido. Intenta de nuevo.')
        except (TypeError, ValueError):
            raise Rechazo('Formato de envío no válido.')
        tipo = str(meta.get('tipo') or '')
        if tipo in ('whatsapp', 'prueba'):
            raise Rechazo('Tipo de solicitud desconocido.')
        return crear(tipo, pares, archivos=archivos, meta=meta, origen='web')

    def solicitud_interna(self, largo):
        token = leer_token()
        dado = self.headers.get('X-Mendiautos-Token', '')
        if not token or not hmac.compare_digest(token, dado):
            raise Rechazo('No autorizado.', 403)
        try:
            cuerpo = json.loads(self.rfile.read(largo).decode('utf-8', 'replace') or '{}')
        except ValueError:
            raise Rechazo('Formato no válido.')
        if not isinstance(cuerpo, dict):
            raise Rechazo('Formato no válido.')
        tipo = cuerpo.get('tipo') or 'whatsapp'
        return crear(tipo, cuerpo.get('datos') or [], cuerpo.get('contacto') or {},
                     meta={'pagina': cuerpo.get('pagina') or 'WhatsApp', 'consentimiento': cuerpo.get('consentimiento')},
                     origen=texto(cuerpo.get('origen') or 'whatsapp', 30))


def cmd_servir(a):
    preparar_carpetas()
    servidor = ThreadingHTTPServer((a.host, a.puerto), Receptor)
    servidor.daemon_threads = True
    print(f'Receptor de solicitudes en http://{a.host}:{a.puerto} · datos en {DATOS}', file=sys.stderr)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


# ------------------------------------------------------------ usuario y sudo
def quien_llama():
    return os.environ.get('SUDO_USER') or pwd.getpwuid(os.getuid()).pw_name


def es_admin():
    return ES_ADMIN


ES_ADMIN = False
SOLO_ADMIN = {'documentos', 'limpiar', 'servir'}


def como_dueno(argv):
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
        os.environ.update(HOME=str(DATOS), USER=DUENO, LOGNAME=DUENO)
        return
    comando = RUTA_COMANDO if os.path.exists(RUTA_COMANDO) else os.path.abspath(sys.argv[0])
    try:
        permitido = subprocess.run(['sudo', '-n', '-l', '-u', DUENO, comando], capture_output=True).returncode == 0
    except FileNotFoundError:
        raise Fallo('Falta sudo en el servidor.')
    if not permitido:
        raise Fallo(f'El usuario {pwd.getpwuid(os.getuid()).pw_name} no tiene permiso para ver las solicitudes. '
                    'El administrador lo habilita con: mendiautos hermes')
    sys.stdout.flush()
    r = subprocess.run(['sudo', '-n', '-u', DUENO, '--', comando, *argv], stdin=subprocess.DEVNULL)
    raise SystemExit(r.returncode)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f'Error: {message}\nAyuda: solicitudes --help\n')


def construir_parser():
    p = Parser(prog='solicitudes', description='Solicitudes de clientes que llegan desde el sitio de Mendiautos.',
               epilog='Las solicitudes se nombran S-<número> (por ejemplo S-1024; también sirve «1024»).')
    sub = p.add_subparsers(dest='comando', metavar='comando', parser_class=Parser)
    sub.required = True

    def nuevo(nombre, ayuda, func):
        s = sub.add_parser(nombre, help=ayuda, description=ayuda)
        s.set_defaults(func=func)
        return s

    s = nuevo('listar', 'lista las solicitudes pendientes (o todas)', cmd_listar)
    s.add_argument('--todas', action='store_true', help='incluir atendidas y descartadas')
    s.add_argument('--estado', choices=ESTADOS)
    s.add_argument('--tipo', choices=sorted(TIPOS))
    s.add_argument('--buscar', metavar='TEXTO', help='nombre, celular, marca…')
    s.add_argument('-n', type=int, default=20, help='cuántas mostrar (por defecto 20)')
    s = nuevo('pendientes', 'lo mismo que «listar»', cmd_listar)
    s.set_defaults(todas=False, estado=None, tipo=None, buscar=None, n=20)

    s = nuevo('ver', 'muestra una solicitud completa', cmd_ver)
    s.add_argument('id', metavar='S-<n>')
    s.add_argument('--completo', action='store_true', help='datos sensibles y documentos (solo administrador)')

    s = nuevo('atender', 'marca una solicitud como atendida', cmd_atender)
    s.add_argument('id', metavar='S-<n>')
    s.add_argument('--nota', default='', help='qué se hizo (queda en el historial)')

    s = nuevo('estado', 'cambia el estado: nueva, en-curso, atendida o descartada', cmd_estado)
    s.add_argument('id', metavar='S-<n>')
    s.add_argument('estado', metavar='estado')
    s.add_argument('--nota', default='')

    s = nuevo('nota', 'agrega una nota al historial', cmd_nota)
    s.add_argument('id', metavar='S-<n>')
    s.add_argument('texto')

    s = nuevo('resumen', 'resumen del día: recibidas y pendientes', cmd_resumen)
    s.add_argument('--dias', type=int, default=1)
    s.add_argument('--silencioso-si-vacio', action='store_true', help='no imprimir nada si no hay novedades')

    s = nuevo('avisar', 'avisos para un canal (lo usan las tareas programadas)', cmd_avisar)
    s.add_argument('--canal', required=True, help='telegram, whatsapp…')
    s.add_argument('--max', type=int, default=5)
    s.add_argument('--reintentar', action='store_true', help='volver a avisar la última tanda (no llegó al chat)')

    nuevo('probar', 'crea una solicitud de prueba para revisar los avisos', cmd_probar)

    s = nuevo('documentos', 'copia los documentos privados de una solicitud (administrador)', cmd_documentos)
    s.add_argument('id', metavar='S-<n>')
    s.add_argument('--destino', required=True, help='carpeta donde dejarlos')

    s = nuevo('limpiar', 'retención: borra documentos y solicitudes viejas (administrador)', cmd_limpiar)
    s.add_argument('--dias-documentos', type=int, default=90)
    s.add_argument('--dias-solicitudes', type=int, default=730)

    s = nuevo('servir', 'receptor HTTP de los formularios (lo corre systemd)', cmd_servir)
    s.add_argument('--host', default='127.0.0.1')
    s.add_argument('--puerto', type=int, default=8781)
    return p


def main(argv=None):
    global ES_ADMIN
    argv = list(sys.argv[1:] if argv is None else argv)
    os.umask(0o027)
    try:
        sys.stdout.reconfigure(errors='replace')
    except AttributeError:
        pass
    args = construir_parser().parse_args(argv)
    try:
        ES_ADMIN = os.geteuid() == 0 or ('SUDO_USER' not in os.environ and
                                         pwd.getpwuid(os.geteuid()).pw_name == DUENO)
        if args.comando in SOLO_ADMIN and not ES_ADMIN:
            raise Fallo('Este comando es solo para el administrador del servidor.')
        if not (args.comando == 'documentos' and os.geteuid() == 0):  # root copia a donde quiera
            como_dueno(argv)
        args.func(args)
    except Fallo as e:
        print(f'Error: {e}', file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 1
    except OSError as e:
        print(f'Error del sistema: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
