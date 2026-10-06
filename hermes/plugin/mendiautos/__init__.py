"""Mendiautos · herramientas del asistente del equipo, con permisos por persona.

El modelo solo recibe estas herramientas (y «clarify», para los botones de
Sí / No / Publicar):

  catalogo      autos del sitio, portada, destacados y videos (comando catalogo)
  solicitudes   lo que llega por los formularios del sitio (comando solicitudes)
  menu          abre el menú con botones de Telegram según el rol

Quién escribe lo sabe Hermes (el ID de Telegram del mensaje), no el modelo:
esta extensión lo lee de la sesión, busca su rol en /etc/mendiautos/equipo.json
y lo pasa a los comandos con --por, que vuelven a revisar el permiso. El
asistente no tiene terminal ni archivos, así que no puede saltarse esto.

Además, el sistema (no solo las instrucciones) hace cumplir que:
  - un auto se publica solo si la persona escribió o tocó «Publicar»;
  - vender, borrar, quitar fotos y poner un video (en la portada o en la
    ficha de un auto) esperan la confirmación de la persona en un mensaje
    posterior («sí», «confirmo»…).

Y limpia lo que llega al chat: las preguntas con botones salen con saltos de
línea reales y sin Markdown (Telegram las muestra tal cual), y las respuestas
no llevan «\\n» escrito ni el razonamiento del modelo en inglés.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import shlex
import subprocess
import threading
import time
import unicodedata
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

EQUIPO = Path(os.environ.get('MENDIAUTOS_EQUIPO') or '/etc/mendiautos/equipo.json')
CMD_CATALOGO = os.environ.get('MENDIAUTOS_CMD_CATALOGO') or '/usr/local/bin/catalogo'
CMD_SOLICITUDES = os.environ.get('MENDIAUTOS_CMD_SOLICITUDES') or '/usr/local/bin/solicitudes'
TZ = dt.timezone(dt.timedelta(hours=-5))
HERRAMIENTAS = {'catalogo', 'solicitudes', 'menu', 'clarify'}
MAX_SALIDA = 8000

ROLES_TODO = ('administrador', 'gerente')
MENU = {
    'administrador': ['🚗 Subir auto', '✏️ Editar auto', '📸 Fotos y videos', '✅ Marcar vendido',
                      '🏠 Portada', '📊 Informe', '📥 Solicitudes', '⭐ Destacados'],
    'vendedor': ['🚗 Subir auto', '✏️ Editar mis autos', '📸 Fotos y videos', '📝 Mis borradores'],
}
MENU['gerente'] = MENU['administrador']

CATALOGO_PERMITIDOS = {
    'listar', 'ver', 'campos', 'faltan', 'agregar', 'editar', 'publicar', 'disponible', 'vender', 'reactivar',
    'ocultar', 'destacar', 'destacados', 'mover', 'eliminar', 'previa', 'borradores', 'foto', 'linea',
    'portada', 'servicios', 'resumen', 'informe', 'precios', 'historial', 'deshacer', 'validar',
}
SOLICITUDES_PERMITIDOS = {'listar', 'ver', 'atender', 'estado', 'nota', 'resumen', 'informe'}
PROHIBIDAS = ('--por', '--carpeta', '--entrada-interna', '--json', '--completo', '--destino')
CAMPOS_VIDEO = {'video', 'reel', 'instagram', 'youtube', 'video_recorrido'}

# Textos de Hermes que ve el equipo, en lenguaje sencillo: /new y /stop en el botón «Menú» de
# Telegram, y la respuesta de /new sin datos técnicos (modelo, proveedor, consejos de Hermes).
DE_CERO = '✨ Listo, empezamos de cero. Los borradores siguen guardados. Escribe «menú» para ver las opciones.'
TEXTOS_ES = {
    'slash.new.description': 'Empezar de cero (los borradores no se pierden)',
    'slash.stop.description': 'Detener lo que estoy haciendo',
    'gateway.reset.header_default': DE_CERO,
    'gateway.reset.header_new': DE_CERO,
    'gateway.reset.tip': '',
    'gateway.session.auto_reset_notice': ('◐ La conversación anterior se cerró y empezamos de cero. Los '
                                          'borradores siguen guardados. Escribe «menú» para ver las opciones.'),
    **dict.fromkeys(('gateway.session.info_model', 'gateway.session.info_provider', 'gateway.session.info_context',
                     'gateway.session.info_acting_model', 'gateway.session.info_endpoint'), ''),
    # Preguntas con botones: sin «Responde "skip"…» (al equipo no le sirve) y el botón de respuesta
    # libre en español.
    'gateway.clarify.skip_hint': '',
    'platform.telegram.prompt.other': '✏️ Otra respuesta',
}


class Rechazo(Exception):
    """Algo que el modelo debe explicarle a la persona o corregir."""


# ---------------------------------------------------------------- utilidades
def sin_acentos(s):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(s)) if not unicodedata.combining(c))


def normal(s):
    return re.sub(r'\s+', ' ', sin_acentos(s).lower()).strip()


def respuesta(ok, salida, **extra):
    salida = (salida or '').strip()
    if len(salida) > MAX_SALIDA:
        salida = salida[:MAX_SALIDA] + '\n… (salida recortada)'
    return json.dumps({'ok': ok, 'salida': salida, **extra}, ensure_ascii=False)


# ---------------------------------------------------- texto limpio en el chat
# Las preguntas con botones (clarify) llegan a Telegram como HTML escapado: el
# Markdown sale tal cual («**Resumen**») y un «\n» escrito por el modelo se ve
# como «\n» y se pega a los enlaces, que dejan de abrir el auto. Las respuestas
# normales sí interpretan Markdown, pero también pueden traer «\n» escrito o el
# razonamiento del modelo en inglés, que nunca debe llegar al equipo.
RE_SALTO_ESCRITO = re.compile(r'(?:\\+r)?\\+n')
RE_ENLACE_MD = re.compile(r'\[([^\]\n]{1,200})\]\((https?://[^\s)]+)\)')
RE_MARCAS_MD = re.compile(r'\*\*|__|~~|`')
RE_TITULO_MD = re.compile(r'^[ \t]*(?:#{1,6}[ \t]+)+', re.M)
RE_VINETA_MD = re.compile(r'^[ \t]*(?:[*+-][ \t]+)+', re.M)
RE_RECOMENDADO = re.compile(r'[ \t]*\((?:recommended|recomendad[oa])\)', re.I)
RE_PALABRA = re.compile(r"[a-záéíóúñü]+(?:['’][a-z]+)?", re.I)
# Una respuesta en inglés pegada a la buena: «…(vendido el 5 de octubre)Aquí tienes…».
RE_PEGADO = re.compile(r'[a-záéíóúñ0-9)\].!?:](?=[A-ZÁÉÍÓÚÑ¿¡][a-záéíóúñ]{2,})')
# Palabras que solo se usan en inglés (sin «a», «no», «he», «has», «me», que también son español).
PALABRAS_EN = frozenset("""
the and or but if then so to of in on at for with from by is are was were be been being it its this that these
those there here we you she they them our your their let let's lets should would could will can must need needs
do does did done have had not yes wait answer answers response respond reply format formatting nicely user asked
asks ask following follow preference preferences show shows showing list listing sold today now first next also
just only which what when where who why how about because since than into
""".split())
PALABRAS_ES = frozenset("""
el la los las un una unos unas y o pero si de del al en con por para sin sobre es son fue está están hay que qué
como cómo cuando donde quien cual cuál cuáles este esta estos estas ese esa eso aquí ya muy más menos también solo
tu tus te mi mis nos lo le les se su sus auto autos carro carros foto fotos precio vendido vendidos tienes tiene
quieres puedes listo hoy dime
""".split())


def saltos_reales(texto):
    """«\\n» escrito como texto → salto de línea de verdad, sin espacios sobrantes ni más de una línea en blanco."""
    t = str(texto or '').replace('\r\n', '\n').replace('\r', '\n')
    t = RE_SALTO_ESCRITO.sub('\n', t)
    t = re.sub(r'[ \t]+\n', '\n', t)
    return re.sub(r'\n{3,}', '\n\n', t).strip()


def texto_plano(texto):
    """Para las preguntas con botones, que Telegram muestra sin formato. Primero se quitan las marcas (si no,
    al quitar «**» de «\\**n» aparecería un «\\n» nuevo) y después se arreglan los saltos de línea. Se repite
    hasta que no cambie: quitar algo puede dejar a la vista otra marca («*(Recommended)*» → «**»)."""
    t = str(texto or '')
    for _ in range(10):
        antes = t
        t = RE_ENLACE_MD.sub(lambda m: f'{m.group(1)}: {m.group(2)}', t)
        t = RE_RECOMENDADO.sub('', RE_MARCAS_MD.sub('', t))
        t = saltos_reales(t)
        t = RE_VINETA_MD.sub('• ', RE_TITULO_MD.sub('', t)).strip()
        if t == antes:
            break
    return t


def opcion_plana(texto):
    """Una opción de botón: una sola línea, sin formato."""
    return ' '.join(texto_plano(texto).split())


def es_ingles(linea):
    """Una línea en inglés: el modelo dejó ver su razonamiento («Let's answer…»)."""
    palabras = [p.lower().replace('’', "'") for p in RE_PALABRA.findall(linea)]
    en = sum(p in PALABRAS_EN for p in palabras)
    es = sum(p in PALABRAS_ES for p in palabras)
    return (en >= 2 and es == 0) or (en >= 3 and en >= 2 * es)


def quitar_ingles(texto):
    """Quita las líneas en inglés. Si un borrador quedó pegado a la respuesta, deja solo la respuesta."""
    lineas = texto.split('\n')
    ingles = [bool(l.strip()) and es_ingles(l) for l in lineas]
    if not any(ingles):
        return texto
    ultima = max(i for i, m in enumerate(ingles) if m)
    quedan = []
    for i, (linea, m) in enumerate(zip(lineas, ingles)):
        if m:
            continue
        if i == ultima + 1:
            p = RE_PEGADO.search(linea)
            if p and p.end() < len(linea):
                linea = linea[p.end():]
        quedan.append(linea)
    limpio = re.sub(r'\n{3,}', '\n\n', '\n'.join(quedan)).strip()
    if not limpio:
        return texto      # todo era inglés: mejor un mensaje que ninguno (queda en el registro)
    logger.warning('mendiautos: quité %d línea(s) en inglés de una respuesta', sum(ingles))
    return limpio


def limpiar_pregunta(p):
    if not isinstance(p, dict):
        return p
    q = dict(p)
    if isinstance(q.get('question'), str):
        q['question'] = texto_plano(q['question']) or q['question']
    if isinstance(q.get('choices'), list):
        q['choices'] = [(opcion_plana(c) or c) if isinstance(c, str) else c for c in q['choices']]
    return q


def limpiar_clarify(args):
    """Los cambios para que la pregunta con botones se lea bien en Telegram, o None si ya está bien."""
    if not isinstance(args, dict):
        return None
    cambios = {}
    if isinstance(args.get('questions'), list):
        nuevas = [limpiar_pregunta(p) for p in args['questions']]
        if nuevas != args['questions']:
            cambios['questions'] = nuevas
    if isinstance(args.get('question'), str) or isinstance(args.get('choices'), list):
        sola = limpiar_pregunta({k: args[k] for k in ('question', 'choices') if k in args})
        cambios.update({k: v for k, v in sola.items() if v != args.get(k)})
    return cambios or None


def eleccion_clarify(resultado):
    """Lo que la persona tocó o escribió en una pregunta con botones. Hermes lo devuelve como
    {"responses": [{"user_response": "Publicar", "status": "answered"}]} (antes, plano)."""
    try:
        datos = json.loads(resultado) if isinstance(resultado, str) else (resultado or {})
    except ValueError:
        return ''
    if not isinstance(datos, dict):
        return ''
    directa = datos.get('user_response') or datos.get('response')
    if isinstance(directa, str) and directa.strip():
        return RE_RECOMENDADO.sub('', directa).strip()
    elegidas = []
    for r in datos.get('responses') or []:
        if not isinstance(r, dict) or r.get('status', 'answered') != 'answered':
            continue
        v = r.get('user_response')
        if isinstance(v, list):
            v = ', '.join(str(x) for x in v)
        if isinstance(v, str) and v.strip():
            elegidas.append(RE_RECOMENDADO.sub('', v).strip())
    return ' · '.join(elegidas)


_cache_equipo = {'mtime': None, 'datos': {}}


def equipo():
    try:
        mtime = EQUIPO.stat().st_mtime
    except OSError:
        return {}
    if _cache_equipo['mtime'] != mtime:
        try:
            datos = json.loads(EQUIPO.read_text('utf-8'))
            miembros = {str(m['id']): {'id': str(m['id']), 'nombre': str(m.get('nombre') or ''), 'rol': m.get('rol')}
                        for m in (datos.get('miembros') or []) if isinstance(m, dict) and m.get('id')}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            miembros = {}
        _cache_equipo.update(mtime=mtime, datos=miembros)
    return _cache_equipo['datos']


def quien():
    """(miembro, plataforma) de quien escribe en esta sesión. Sin sesión: (None, '')."""
    try:
        from gateway.session_context import get_session_env
    except ImportError:
        return None, ''
    uid = (get_session_env('HERMES_SESSION_USER_ID') or '').strip()
    plataforma = (get_session_env('HERMES_SESSION_PLATFORM') or '').strip().lower()
    if not uid or plataforma != 'telegram':
        return None, plataforma
    return equipo().get(uid), plataforma


# ------------------------------------------- lo que dijo la persona (turnos)
# Por persona: cuántos mensajes van, el último texto (o botón) y lo pendiente
# de confirmar. Vive en memoria: si Hermes se reinicia, hay que volver a pedir.
_estado = {}
_candado = threading.Lock()

RE_PUBLICAR = re.compile(r'\bpublica(?:r|lo|la|los|las)?\b')
RE_NO_PUBLICAR = re.compile(r'\b(?:no|nunca|todavia no|aun no|ni)\b[^.!]{0,25}\bpublica')
RE_SI = re.compile(r'^(?:si|s|sii+|dale|confirmo|confirmado|confirmar|correcto|de una|hagale|ok|okay|listo|'
                   r'claro|asi es|exacto|eso|afirmativo|va|hazlo|adelante|por favor|vendido|borralo|quitalas|'
                   r'quitala|ponlo|ponla|de acuerdo)\b')
RE_DUDA = re.compile(r'\b(?:no|espera|cancela|cancelar|todavia|aun no|mejor no|pera|momento)\b')


def autoriza_publicar(texto):
    t = normal(texto)
    return bool(t) and '?' not in t and bool(RE_PUBLICAR.search(t)) and not RE_NO_PUBLICAR.search(t)


def es_si(texto):
    t = re.sub(r'^[^a-z0-9]+', '', normal(texto))      # sin emojis ni signos al comienzo
    return bool(RE_SI.match(t)) and not RE_DUDA.search(t)


def anotar(uid, texto):
    with _candado:
        e = _estado.setdefault(uid, {'turno': 0, 'texto': '', 'publicar': False, 'pendiente': None})
        e['turno'] += 1
        e['texto'] = str(texto or '')[:2000]
        e['publicar'] = autoriza_publicar(e['texto'])
        e['cuando'] = time.time()


def estado(uid):
    with _candado:
        return _estado.setdefault(uid, {'turno': 0, 'texto': '', 'publicar': False, 'pendiente': None})


# ------------------------------------------------------------ los comandos
def entorno():
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
           'HOME': os.environ.get('HOME', '/tmp'), 'HERMES_HOME': os.environ.get('HERMES_HOME', '')}
    env.update({k: v for k, v in os.environ.items() if k.startswith('MENDIAUTOS_') and k not in (
        'MENDIAUTOS_EQUIPO', 'MENDIAUTOS_CMD_CATALOGO', 'MENDIAUTOS_CMD_SOLICITUDES')})
    if os.environ.get('MENDIAUTOS_EQUIPO'):
        env['MENDIAUTOS_EQUIPO'] = os.environ['MENDIAUTOS_EQUIPO']
    return env


def correr(comando, args, tiempo=120):
    try:
        r = subprocess.run([comando, *args], capture_output=True, text=True, timeout=tiempo, env=entorno(),
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, 'El comando tardó demasiado y se canceló; intenta de nuevo en un momento.'
    except OSError as e:
        return False, f'No pude ejecutar {os.path.basename(comando)}: {e}'
    return r.returncode == 0, (r.stdout + ('\n' + r.stderr if r.stderr else '')).strip()


def partir(orden, nombre):
    try:
        args = shlex.split(str(orden or ''))
    except ValueError:
        raise Rechazo('No entendí la orden: revisa que las comillas estén cerradas.')
    while args and args[0] in ('sudo', nombre, f'/usr/local/bin/{nombre}'):
        args = args[1:]
    if not args:
        raise Rechazo(f'Falta la orden, por ejemplo: {"listar" if nombre == "catalogo" else "listar"}')
    for a in args:
        if any(a == p or a.startswith(p + '=') for p in PROHIBIDAS):
            raise Rechazo(f'La opción {a.split("=")[0]} no está disponible para el asistente.')
    return args


def carpetas_permitidas():
    home = Path(os.environ.get('HERMES_HOME') or Path.home() / '.hermes')
    return [(home / d).resolve() for d in ('cache/images', 'cache/videos', 'cache/documents', 'cache/video',
                                           'image_cache', 'document_cache', 'video_cache')]


def revisar_archivos(args):
    """Las fotos y videos solo pueden venir del caché de lo que llegó por Telegram."""
    permitidas = carpetas_permitidas()
    for a in args:
        if a.startswith('-') or not ('/' in a or a.startswith('~')):
            continue
        ruta = Path(a).expanduser()
        try:
            real = ruta.resolve(strict=True)
        except (OSError, RuntimeError):
            raise Rechazo(f'No encuentro el archivo {a}. Lo que llega por Telegram se borra a las 24 horas: '
                          'pide que lo envíen de nuevo.')
        if not ruta.is_absolute() or not any(real.is_relative_to(c) for c in permitidas) or not real.is_file():
            raise Rechazo(f'{a} no es una foto o un video recibido por el chat; solo se publican esos.')


def confirmacion_propia(args):
    """Texto para confirmar con la persona, o None si la orden no lo necesita (o lo pide el comando)."""
    sub = args[0]
    if sub == 'foto' and len(args) > 2 and args[1] == 'quitar':
        cuales = 'todas las fotos' if '--todas' in args else 'las fotos ' + ', '.join(
            x for x in args[3:] if not x.startswith('-'))
        return f'Vas a quitar {cuales} de «{args[2]}». ¿Confirmas?'
    if sub == 'portada' and len(args) > 1 and args[1] in ('foto', 'video'):
        return (f'{"Este video" if args[1] == "video" else "Esta foto"} irá en: el fondo de la portada del inicio '
                '(lo ve todo el que entra al sitio). ¿Confirmas?')
    if sub == 'editar' and len(args) > 2:
        for a in args[2:]:
            campo, igual, valor = a.partition('=')
            if igual and normal(campo).replace(' ', '_') in CAMPOS_VIDEO:
                if normal(valor) in ('', 'borrar', 'quitar', 'eliminar'):
                    return f'Vas a quitar el video de la ficha de «{args[1]}». ¿Confirmas?'
                return f'Este video irá en: la ficha de «{args[1]}». ¿Confirmas?'
    return None


def herramienta_catalogo(args_modelo, **_):
    m, plataforma = quien()
    if not m:
        return respuesta(False, 'No sé quién escribe o no está en el equipo, así que no hice nada. '
                                'El administrador agrega a las personas con: mendiautos equipo agregar …')
    try:
        args = partir(args_modelo.get('orden'), 'catalogo')
        sub = args[0]
        if sub in ('--help', '-h', 'ayuda'):
            ok, salida = correr(CMD_CATALOGO, ['--help'])
            return respuesta(ok, salida)
        if sub not in CATALOGO_PERMITIDOS:
            raise Rechazo(f'«{sub}» no está disponible por chat.')
        if (sub == 'foto' and len(args) > 1 and args[1] == 'agregar') or \
                (sub == 'portada' and len(args) > 1 and args[1] in ('foto', 'video')):
            revisar_archivos(args[2:])
        e = estado(m['id'])
        confirmar = '--confirmar' in args
        base = [a for a in args if a != '--confirmar']
        pregunta = confirmacion_propia(base)

        if sub in ('publicar', 'disponible'):
            if not e['publicar']:
                raise Rechazo('No publiqué: solo se publica cuando la persona escribe o toca «Publicar». '
                              'Muéstrale el resumen y la vista previa, y pregúntale con clarify '
                              '(opciones: «Publicar», «Corregir algo»).')
            ok, salida = correr(CMD_CATALOGO, args + ['--por', m['id']])
            if ok:
                with _candado:
                    e['publicar'] = False   # una palabra «Publicar» sirve para una publicación
            return respuesta(ok, salida)

        if pregunta or sub in ('vender', 'eliminar'):
            if not confirmar:
                if pregunta:        # la confirma la extensión: el comando no la pide
                    with _candado:
                        e['pendiente'] = {'orden': base, 'turno': e['turno']}
                    return respuesta(False, 'Todavía no hice nada. Pregúntale a la persona esto (puedes usar '
                                            'clarify con «Sí» y «No»): ' + pregunta + ' Si confirma, repite la '
                                            'misma orden agregando --confirmar.', necesita_confirmacion=True)
                ok, salida = correr(CMD_CATALOGO, base + ['--por', m['id']])
                hallado = re.search(rf'catalogo {sub} (\S+)', salida)
                if ok and hallado:
                    with _candado:
                        e['pendiente'] = {'orden': [sub, hallado.group(1)], 'turno': e['turno']}
                    salida += ('\nTodavía no hice el cambio: muéstrale este detalle a la persona y pregúntale si '
                               'confirma (clarify con «Sí» y «No»). Si confirma, repite con --confirmar.')
                return respuesta(ok, salida, necesita_confirmacion=ok and bool(hallado))
            with _candado:
                p = e['pendiente']
                clave = base if pregunta else [sub, base[1] if len(base) > 1 else '']
                if p and not pregunta and p['orden'][0] == sub and p['orden'][1] != clave[1]:
                    raise Rechazo(f'Para confirmar usa el id exacto que mostró la confirmación: {p["orden"][1]}.')
                if not p or p['orden'][:2] != clave[:2] or (pregunta and p['orden'] != base):
                    raise Rechazo('No lo hice: primero hay que mostrarle a la persona qué se va a hacer y esperar '
                                  'que confirme. Repite la orden sin --confirmar para ver la confirmación.')
                if e['turno'] <= p['turno'] or not es_si(e['texto']):
                    raise Rechazo('No lo hice: la persona todavía no confirmó en un mensaje nuevo '
                                  '(«sí», «confirmo»). Pregúntale y espera su respuesta.')
                e['pendiente'] = None
            extra = ['--confirmar'] if sub in ('vender', 'eliminar') else []
            ok, salida = correr(CMD_CATALOGO, base + extra + ['--por', m['id']], tiempo=900)
            return respuesta(ok, salida)

        tiempo = 900 if sub == 'portada' else 180
        ok, salida = correr(CMD_CATALOGO, args + ['--por', m['id']], tiempo=tiempo)
        return respuesta(ok, con_pistas(args, ok, salida))
    except Rechazo as r:
        return respuesta(False, str(r))


PISTA_DATO = ('[Sistema, no lo menciones] No inventes ni supongas el valor: dile a la persona qué no se pudo '
              'guardar y pregúntale el dato correcto con un ejemplo de lo que se acepta.')
PISTA_OCUPADO = ('[Sistema, no lo menciones] Otro cambio estaba en curso. Espera un momento y repite la orden una '
                 'vez; si vuelve a pasar, díselo a la persona.')


def con_pistas(args, ok, salida):
    """Lo que el modelo necesita saber para seguir bien, sin que la persona lo vea."""
    if not ok and 'ocupado' in salida:
        return salida + '\n' + PISTA_OCUPADO
    if not ok and 'Error' in salida:
        return salida + '\n' + PISTA_DATO
    if ok and args[:2] == ['foto', 'listar']:
        archivos = re.findall(r'^\s*archivo:\s*(\S+)\s*$', salida, re.M)
        if archivos:
            return (salida + '\n[Sistema, no lo menciones] Para mostrarle las fotos en el chat, pon estas líneas '
                    'tal cual al final de tu respuesta, en este orden, y antes di el número de cada una (nunca '
                    'mandes los enlaces ni los nombres de archivo):\n' + '\n'.join(f'MEDIA:{a}' for a in archivos))
    return salida


def herramienta_solicitudes(args_modelo, **_):
    m, _plataforma = quien()
    if not m:
        return respuesta(False, 'No sé quién escribe o no está en el equipo, así que no hice nada.')
    if m['rol'] not in ROLES_TODO:
        return respuesta(False, 'Las solicitudes de los clientes las ven el gerente y el administrador.')
    try:
        args = partir(args_modelo.get('orden'), 'solicitudes')
        if args[0] not in SOLICITUDES_PERMITIDOS:
            raise Rechazo(f'«{args[0]}» no está disponible por chat.')
        if args[0] in ('atender', 'estado', 'nota'):
            args += ['--por', m['nombre'] or m['id']]
        ok, salida = correr(CMD_SOLICITUDES, args)
        return respuesta(ok, salida)
    except Rechazo as r:
        return respuesta(False, str(r))


def prefijo_telegram():
    """https://api.telegram.org/bot, o el servidor propio de la API si Hermes usa uno (telegram.extra.base_url)."""
    try:
        import yaml
        ruta = Path(os.environ.get('HERMES_HOME') or Path.home() / '.hermes') / 'config.yaml'
        cfg = yaml.safe_load(ruta.read_text('utf-8')) or {}
        base = str(((cfg.get('telegram') or {}).get('extra') or {}).get('base_url') or '').strip()
        if base.startswith(('http://', 'https://')):
            return base
    except Exception:
        pass
    return 'https://api.telegram.org/bot'


def telegram(metodo, datos):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        raise OSError('falta el token del bot')
    req = urllib.request.Request(f'{prefijo_telegram()}{token}/{metodo}', data=json.dumps(datos).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode('utf-8'))


def herramienta_menu(args_modelo, **_):
    m, _plataforma = quien()
    if not m:
        return respuesta(False, 'No sé quién escribe o no está en el equipo.')
    opciones = MENU.get(m['rol'], MENU['vendedor'])
    teclado = {'keyboard': [[{'text': t} for t in opciones[i:i + 2]] for i in range(0, len(opciones), 2)],
               'resize_keyboard': True, 'is_persistent': True,
               'input_field_placeholder': 'Elige una opción o escríbeme'}
    texto = str(args_modelo.get('texto') or '').strip()[:500] or 'Elige una opción del menú 👇'
    try:
        r = telegram('sendMessage', {'chat_id': m['id'], 'text': texto, 'reply_markup': teclado})
        if not r.get('ok'):
            raise OSError(r.get('description') or 'Telegram no aceptó el mensaje')
    except (OSError, ValueError) as e:
        logger.warning('mendiautos: no pude enviar el menú: %s', e)
        return respuesta(False, 'No pude mostrar los botones. Escribe el menú como lista numerada.',
                         opciones=opciones)
    return respuesta(True, 'Ya envié el menú con botones (con tu texto). No lo repitas: responde solo algo muy '
                           'corto o nada más.', opciones=opciones)


# ------------------------------------------------------------------ ganchos
def antes_de_llamar_al_modelo(user_message='', sender_id='', platform='', **_):
    """Anota lo que dijo la persona y le recuerda al modelo quién es y qué puede hacer."""
    if not sender_id or str(platform).lower() not in ('telegram', ''):
        return None
    m = equipo().get(str(sender_id))
    anotar(str(sender_id), user_message)
    ahora = dt.datetime.now(TZ)
    dias = 'lunes martes miércoles jueves viernes sábado domingo'.split()
    meses = ('enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre '
             'diciembre').split()
    fecha = f'{dias[ahora.weekday()]} {ahora.day} de {meses[ahora.month - 1]} de {ahora.year}, {ahora:%H:%M}'
    if not m:
        return {'context': f'[Sistema] Quien escribe no está en el equipo de Mendiautos. No hagas nada por esta '
                           f'persona: dile que pida acceso al administrador. Hoy es {fecha}.'}
    extra = ('' if m['rol'] in ROLES_TODO else
             ' Es vendedor: sube autos y corrige los que él subió; no marca vendidos, no cambia la portada ni los '
             'destacados y no ve solicitudes ni informes (el sistema lo bloquea igual).')
    return {'context': f'[Sistema, no lo menciones] Te escribe {m["nombre"] or "alguien del equipo"} '
                       f'({m["rol"]}). Hoy es {fecha} (hora de Colombia).{extra}'}


def antes_de_herramienta(tool_name='', args=None, **_):
    if tool_name not in HERRAMIENTAS:
        return {'action': 'block', 'message': f'La herramienta {tool_name} no está disponible en este asistente.'}
    if tool_name == 'clarify':
        cambios = limpiar_clarify(args)
        if cambios:
            return {'action': 'modify', 'args': cambios}
    return None


def despues_de_herramienta(tool_name='', result=None, **_):
    """Lo que la persona toca en los botones de clarify cuenta como su respuesta («Publicar», «Sí»)."""
    if tool_name != 'clarify':
        return
    m, _plataforma = quien()
    if not m:
        return
    eleccion = eleccion_clarify(result)
    if eleccion:
        anotar(m['id'], eleccion)


def limpiar_respuesta(response_text='', **_):
    """Lo último antes de que la respuesta salga al chat: «\\n» escrito y razonamiento en inglés fuera."""
    if not isinstance(response_text, str) or not response_text.strip():
        return None
    limpio = saltos_reales(response_text)
    for _ in range(5):      # lo que queda al despegar un borrador también puede venir en inglés
        siguiente = quitar_ingles(limpio)
        if siguiente == limpio:
            break
        limpio = siguiente
    return limpio if limpio and limpio != response_text.strip() else None


def quitar_recomendado():
    """Hermes le pega «(Recommended)», en inglés, a la primera opción de cada pregunta con botones. En una
    confirmación («¿Confirmas la venta?» Sí / No) no debe haber una opción «recomendada», así que se apaga."""
    try:
        import tools.clarify_tool as clarify_tool
    except Exception:
        return False
    if not callable(getattr(clarify_tool, 'mark_recommended', None)):
        return False
    clarify_tool.mark_recommended = lambda choices: list(choices)
    return True


def comando_menu(_args=''):
    """/menu, si llega como comando (al_recibir suele convertirlo antes en un mensaje para el asistente)."""
    try:
        enviado = json.loads(herramienta_menu({})).get('ok')
    except ValueError:
        enviado = False
    return None if enviado else 'Escríbeme «menú» y te muestro las opciones 👇'


def al_recibir(event=None, **_):
    """/start y /menu abren el menú (Hermes ignora /start por su cuenta)."""
    texto = str(getattr(event, 'text', '') or '').strip()
    fuente = getattr(event, 'source', None)
    plataforma = str(getattr(getattr(fuente, 'platform', None), 'value', '') or '').lower()
    if plataforma == 'telegram' and re.fullmatch(r'/(start|menu|menú)(@\w+)?', texto, re.I):
        return {'action': 'rewrite', 'text': 'Hola, muéstrame el menú'}
    return None


# -------------------------------------------------------------- esquemas
ESQUEMA_CATALOGO = {
    'name': 'catalogo',
    'description': (
        'Maneja el catálogo de autos del sitio de Mendiautos, la portada del inicio, los destacados y los '
        'videos. Recibe la orden del comando catalogo sin la palabra «catalogo». Ejemplos: '
        '«agregar marca=Mazda modelo=CX-5 anio=2022», «faltan mazda-cx-5-2022», '
        '«editar cx-5 "precio=98,5 millones" km=41000 hp="no aplica"», '
        '«foto agregar cx-5 /ruta/img_1.jpg /ruta/img_2.jpg», «foto orden cx-5 3 1 2», «previa cx-5», '
        '«publicar cx-5», «vender onix», «reactivar onix km=52000 precio=61000000», '
        '«destacar cx-5 --en-lugar-de duster», «portada textos texto=Mazda "titulo=CX-5 | 2022"», '
        '«portada video /ruta/video.mp4», «informe», «informe --mes», «deshacer», «--help». '
        'Quién pide cada cambio lo pone el sistema. Responde en JSON con ok y la salida del comando.'),
    'parameters': {
        'type': 'object',
        'properties': {
            'orden': {'type': 'string', 'description': 'La orden, como en la línea de comandos (usa comillas '
                                                       'para los valores con espacios).'},
        },
        'required': ['orden'],
    },
}
ESQUEMA_SOLICITUDES = {
    'name': 'solicitudes',
    'description': (
        'Solicitudes de los clientes que llegan por los formularios del sitio (solo gerente y administrador). '
        'Recibe la orden del comando solicitudes sin esa palabra. Ejemplos: «listar», «ver 1024», '
        '«estado 1024 en-curso --nota "La tomó Nelson"», «atender 1024 --nota "Le mandé la oferta"», '
        '«nota 1024 "Llamar el lunes"», «resumen --dias 7».'),
    'parameters': {
        'type': 'object',
        'properties': {'orden': {'type': 'string', 'description': 'La orden, como en la línea de comandos.'}},
        'required': ['orden'],
    },
}
ESQUEMA_MENU = {
    'name': 'menu',
    'description': ('Envía a la persona el menú de opciones como botones de Telegram (según su rol), junto con '
                    'un texto corto tuyo. Úsalo al saludar o cuando pidan el menú.'),
    'parameters': {
        'type': 'object',
        'properties': {'texto': {'type': 'string', 'description': 'Saludo o frase corta que acompaña el menú.'}},
    },
}


def register(ctx):
    ctx.register_tool(name='catalogo', toolset='mendiautos', schema=ESQUEMA_CATALOGO,
                      handler=herramienta_catalogo, emoji='🚗')
    ctx.register_tool(name='solicitudes', toolset='mendiautos', schema=ESQUEMA_SOLICITUDES,
                      handler=herramienta_solicitudes, emoji='📥')
    ctx.register_tool(name='menu', toolset='mendiautos', schema=ESQUEMA_MENU, handler=herramienta_menu, emoji='📋')
    ctx.register_hook('pre_llm_call', antes_de_llamar_al_modelo)
    ctx.register_hook('pre_tool_call', antes_de_herramienta)
    ctx.register_hook('post_tool_call', despues_de_herramienta)
    ctx.register_hook('pre_gateway_dispatch', al_recibir)
    ctx.register_hook('transform_llm_output', limpiar_respuesta)
    if not quitar_recomendado():
        logger.warning('mendiautos: esta versión de Hermes no deja quitar el «(Recommended)» de los botones')
    # Botón «Menú» de Telegram en español: el instalador deja ahí solo /menu, /new y /stop.
    # En una versión de Hermes sin estas funciones, el menú sigue como venía.
    try:
        if hasattr(ctx, 'register_command'):
            ctx.register_command('menu', comando_menu, description='Ver el menú con botones')
        if hasattr(ctx, 'register_locale'):
            ctx.register_locale('es', TEXTOS_ES)
    except Exception as e:  # el menú en español es un extra: el asistente funciona sin él
        logger.warning('mendiautos: no pude poner el menú de Telegram en español: %s', e)
