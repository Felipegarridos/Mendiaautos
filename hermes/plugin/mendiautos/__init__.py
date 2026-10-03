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
        return respuesta(ok, salida)
    except Rechazo as r:
        return respuesta(False, str(r))


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


def antes_de_herramienta(tool_name='', **_):
    if tool_name not in HERRAMIENTAS:
        return {'action': 'block', 'message': f'La herramienta {tool_name} no está disponible en este asistente.'}
    return None


def despues_de_herramienta(tool_name='', result=None, **_):
    """Lo que la persona toca en los botones de clarify cuenta como su respuesta."""
    if tool_name != 'clarify':
        return
    m, _plataforma = quien()
    if not m:
        return
    try:
        datos = json.loads(result) if isinstance(result, str) else (result or {})
        eleccion = datos.get('user_response') or datos.get('response') or ''
    except (ValueError, AttributeError):
        eleccion = ''
    if eleccion:
        anotar(m['id'], eleccion)


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
    # Botón «Menú» de Telegram en español: el instalador deja ahí solo /menu, /new y /stop.
    # En una versión de Hermes sin estas funciones, el menú sigue como venía.
    try:
        if hasattr(ctx, 'register_command'):
            ctx.register_command('menu', comando_menu, description='Ver el menú con botones')
        if hasattr(ctx, 'register_locale'):
            ctx.register_locale('es', TEXTOS_ES)
    except Exception as e:  # el menú en español es un extra: el asistente funciona sin él
        logger.warning('mendiautos: no pude poner el menú de Telegram en español: %s', e)
