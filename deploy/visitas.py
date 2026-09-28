#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mendiautos-visitas: cuenta las visitas del sitio a partir de los registros de nginx.

Sin Google Analytics ni cookies: cada noche lee los registros del servidor web
y guarda solo totales por día en /var/lib/mendiautos/visitas/AAAA-MM-DD.json:

  vistas       páginas vistas por personas (sin robots, vistas previas ni monitoreo)
  visitantes   personas distintas en el día (se calcula con una huella que no se guarda)
  paginas      vistas por página
  autos        vistas de la ficha de cada auto (DetalleAuto.dc.html?id=…)

No se guardan direcciones IP ni navegadores. Los informes del asistente
(catalogo informe) suman estos archivos.

  mendiautos-visitas            cuenta los últimos días completos (lo corre un temporizador)
  mendiautos-visitas --dias 14  vuelve a contar los últimos 14 días (si aún hay registros)
"""
import argparse
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path

REGISTROS = [Path(p) for p in (os.environ.get('MENDIAUTOS_REGISTROS') or
                               '/var/log/nginx/mendiautos.access.log:/var/log/nginx/access.log').split(':') if p]
DESTINO = Path(os.environ.get('MENDIAUTOS_VISITAS') or '/var/lib/mendiautos/visitas')
TZ = dt.timezone(dt.timedelta(hours=-5))          # Colombia no tiene horario de verano
CONSERVAR_DIAS = 400

# Formato «combined» de nginx.
LINEA = re.compile(r'^(\S+) \S+ \S+ \[([^\]]+)\] "(\S+) (\S+) [^"]*" (\d{3}) \S+ "[^"]*" "([^"]*)"')
PAGINA = re.compile(r'^/(?:index\.html)?$|^/([A-Za-z]+)\.dc\.html$')
ROBOTS = re.compile(r'bot|crawl|spider|slurp|facebookexternalhit|facebookcatalog|whatsapp|telegram|twitter|'
                    r'linkedin|skype|discord|preview|curl|wget|python|go-http|java/|okhttp|axios|node-fetch|'
                    r'headless|lighthouse|pagespeed|monitor|uptime|pingdom|scan|check|feed|embedly|vkshare|'
                    r'google-read-aloud|mediapartners|bingpreview|yandex|baidu|petal|semrush|ahrefs|mj12', re.I)
RE_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,79}$')


def archivos():
    """Los registros de nginx, del más viejo al más nuevo (incluye los rotados .1, .2.gz…)."""
    res = []
    for base in REGISTROS:
        rotados = []
        for f in base.parent.glob(base.name + '*'):
            m = re.fullmatch(re.escape(base.name) + r'(?:\.(\d+))?(\.gz)?', f.name)
            if m and f.is_file():
                rotados.append((int(m.group(1) or 0), f))
        res += [f for _, f in sorted(rotados, reverse=True)]
    return res


def leer(f):
    abrir = gzip.open if f.suffix == '.gz' else open
    try:
        with abrir(f, 'rt', encoding='utf-8', errors='replace') as h:
            yield from h
    except OSError as e:
        print(f'No pude leer {f}: {e}', file=sys.stderr)


def contar(dias):
    """{fecha: {vistas, huellas, paginas, autos}} para las fechas pedidas."""
    cuentas = {d: {'vistas': 0, 'huellas': set(), 'paginas': {}, 'autos': {}} for d in dias}
    vistos = set()
    for f in archivos():
        try:
            clave_f = (f.stat().st_ino, f.stat().st_dev)
        except OSError:
            continue
        if clave_f in vistos:           # access.log puede ser un enlace al de mendiautos
            continue
        vistos.add(clave_f)
        for linea in leer(f):
            m = LINEA.match(linea)
            if not m:
                continue
            ip, cuando, metodo, ruta, estado, agente = m.groups()
            if metodo != 'GET' or estado not in ('200', '304') or not agente or ROBOTS.search(agente):
                continue
            try:
                fecha = dt.datetime.strptime(cuando, '%d/%b/%Y:%H:%M:%S %z').astimezone(TZ).date()
            except ValueError:
                continue
            c = cuentas.get(fecha)
            if c is None:
                continue
            partes = urllib.parse.urlsplit(ruta)
            pm = PAGINA.match(partes.path)
            if not pm:
                continue
            consulta = urllib.parse.parse_qs(partes.query)
            if 'previa' in consulta:         # vistas previas de borradores: no son visitas
                continue
            pagina = pm.group(1) or 'MendiautosHome'
            c['vistas'] += 1
            c['paginas'][pagina] = c['paginas'].get(pagina, 0) + 1
            c['huellas'].add(hashlib.sha256(f'{ip}|{agente}'.encode()).hexdigest()[:16])
            auto = (consulta.get('id') or [''])[0]
            if pagina == 'DetalleAuto' and RE_ID.match(auto):
                c['autos'][auto] = c['autos'].get(auto, 0) + 1
    return cuentas


def escribir(ruta, datos):
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix='.' + ruta.name + '.')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(datos, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')
    os.chmod(tmp, 0o644)
    os.replace(tmp, ruta)


def main():
    p = argparse.ArgumentParser(prog='mendiautos-visitas', description=__doc__.split('\n')[0])
    p.add_argument('--dias', type=int, default=2, help='cuántos días completos recontar (por defecto 2)')
    a = p.parse_args()
    hoy = dt.datetime.now(TZ).date()
    dias = [hoy - dt.timedelta(days=i) for i in range(1, max(1, min(a.dias, 60)) + 1)]
    DESTINO.mkdir(parents=True, exist_ok=True)
    cuentas = contar(dias)
    for d in sorted(dias):
        c = cuentas[d]
        ruta = DESTINO / f'{d.isoformat()}.json'
        if not c['vistas'] and ruta.exists():
            continue    # ya no quedan registros de ese día: se conserva lo contado antes
        escribir(ruta, {'fecha': d.isoformat(), 'vistas': c['vistas'], 'visitantes': len(c['huellas']),
                        'paginas': c['paginas'], 'autos': c['autos']})
        print(f'{d.isoformat()}: {c["vistas"]} vistas, {len(c["huellas"])} visitantes')
    limite = hoy - dt.timedelta(days=CONSERVAR_DIAS)
    for f in DESTINO.glob('????-??-??.json'):
        try:
            if dt.date.fromisoformat(f.stem) < limite:
                f.unlink()
        except ValueError:
            pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
