"""Pruebas del comando catalogo (deploy/catalogo.py) sobre un catálogo temporal, nunca sobre el real.

Además de las funcionales, hay pruebas de estrés: varias personas cambiando autos a la vez, una ráfaga de
cambios al mismo auto, el candado retenido por otro proceso y flujos completos en paralelo. Necesitan Linux (fcntl), git y Pillow; en GitHub Actions corren solas en cada cambio:

    python -m unittest discover -s deploy/pruebas -v
"""
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CATALOGO = Path(__file__).resolve().parents[1] / 'catalogo.py'
# Solo para depurar en otra máquina: un lanzador que sustituye fcntl/pwd. Sin candado real, así que con él
# no corren las pruebas de estrés.
LANZADOR = os.environ.get('CATALOGO_LANZADOR', '')
ANA, BETO, CARO, VENDEDOR = '111', '222', '333', '999'
CAMPOS = ['version=LX', 'precio=42 millones', 'negociable=no', 'km=35000', 'transmision=Mecánica',
          'combustible=Gasolina', 'carroceria=Hatchback', 'traccion=no aplica', 'motor=1.2', 'color_exterior=Rojo',
          'color_interior=Negro', 'placa_fin=3', 'ciudad=Bucaramanga', 'historial.duenos=1', 'blindado=no',
          'asegurable=sí', 'permuta=no', 'financiacion=sí', 'historial.soat=Enero 2027', 'historial.rtm=Vigente',
          'historial.siniestros=0', 'historial.prenda=Sin prenda', 'historial.comparendos=Sin comparendos',
          'historial.mantenimientos=3', 'hp=83', 'descripcion=Auto de prueba.']


@unittest.skipIf(os.name == 'nt' and not LANZADOR, 'el comando catalogo necesita Linux (fcntl)')
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.datos = base / 'catalogo'
        (base / 'equipo.json').write_text(json.dumps({'miembros': [
            {'id': ANA, 'nombre': 'Ana', 'rol': 'administrador'},
            {'id': BETO, 'nombre': 'Beto', 'rol': 'administrador'},
            {'id': CARO, 'nombre': 'Caro', 'rol': 'gerente'},
            {'id': VENDEDOR, 'nombre': 'Vendedor', 'rol': 'vendedor'}]}), 'utf-8')
        cls.env = dict(os.environ, MENDIAUTOS_CATALOGO=str(cls.datos), MENDIAUTOS_EQUIPO=str(base / 'equipo.json'),
                       MENDIAUTOS_CONF=str(base / 'mendiautos.conf'), MENDIAUTOS_RESPALDOS=str(base / 'respaldos'),
                       MENDIAUTOS_VISITAS=str(base / 'visitas'), MENDIAUTOS_URL='https://pruebas.invalid',
                       PYTHONIOENCODING='utf-8')
        cls.env.pop('SUDO_USER', None)
        from PIL import Image
        cls.fotos = []
        for i in range(22):
            ruta = base / f'foto{i + 1}.jpg'
            Image.new('RGB', (1200, 800), ((i * 11) % 256, (i * 37) % 256, 160)).save(ruta, 'JPEG', quality=85)
            cls.fotos.append(str(ruta))
        cls.falsa = base / 'falsa.jpg'
        cls.falsa.write_text('esto no es una imagen')
        rc, salida = cls.cat('iniciar')
        assert rc == 0, salida

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def cat(cls, *args, por=None, timeout=180):
        comando = [sys.executable] + ([LANZADOR] if LANZADOR else []) + [str(CATALOGO), *args]
        comando += ['--por', por] if por else []
        r = subprocess.run(comando, env=cls.env, capture_output=True, text=True, encoding='utf-8', timeout=timeout)
        return r.returncode, r.stdout + r.stderr

    def ok(self, *args, por=ANA):
        rc, salida = self.cat(*args, por=por)
        self.assertEqual(rc, 0, f'{args}: {salida}')
        return salida

    def falla(self, *args, por=ANA):
        rc, salida = self.cat(*args, por=por)
        self.assertNotEqual(rc, 0, f'{args} debía fallar: {salida}')
        return salida

    def nuevo(self, modelo, por=ANA, completo=True, fotos=0):
        salida = self.ok('agregar', 'marca=Kia', f'modelo={modelo}', 'anio=2021', *(CAMPOS if completo else []), por=por)
        id_ = re.search(r'id: ([a-z0-9-]+)', salida).group(1)
        if fotos:
            self.ok('foto', 'agregar', id_, *self.fotos[:fotos], por=por)
        return id_

    def json_de(self, id_):
        return json.loads(self.ok('ver', id_, '--json', por=None))

    def publicados(self):
        texto = (self.datos / 'inventario.js').read_text('ascii')
        return json.loads(texto[texto.index('['):texto.rindex(']') + 1])

    def integridad(self):
        self.ok('validar', por=None)
        r = subprocess.run(['git', '-C', str(self.datos), 'fsck', '--no-progress'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class Funcional(Base):
    def test_vista_previa_lleva_a_la_ficha_al_publicar_y_vender(self):
        id_ = self.nuevo('Previa', fotos=5)
        clave = self.json_de(id_)['previa']
        previa = self.datos / 'previas' / f'{clave}.js'
        self.assertIn('window.MND_PREVIA', previa.read_text('ascii'))
        self.ok('publicar', id_)
        hacia = f'location.replace("DetalleAuto.dc.html?id={id_}");'
        self.assertIn(hacia, previa.read_text('ascii'))
        self.ok('vender', id_, '--confirmar')
        self.assertIn(hacia, previa.read_text('ascii'))
        self.ok('reactivar', id_, 'km=36000', 'precio=41 millones')
        self.assertIn(hacia, previa.read_text('ascii'))
        self.assertNotIn('previa_publicada', (self.datos / 'inventario.js').read_text('ascii'))
        self.integridad()

    def test_reel_se_pide_como_opcional(self):
        id_ = self.nuevo('Reel', completo=False)
        self.assertIn('Opcional: el reel de Instagram', self.ok('editar', id_, 'km=1000'))
        salida = self.ok('editar', id_, 'video=https://www.instagram.com/reel/AbCdE12345/?stkn=xyz')
        self.assertEqual(self.json_de(id_)['video'], 'https://www.instagram.com/reel/AbCdE12345/')
        self.assertNotIn('reel de Instagram del recorrido (todavía sin enlace)', salida)
        completo = self.nuevo('ReelCompleto', fotos=5)
        self.assertIn('Opcional: todavía no tiene el reel', self.ok('editar', completo, 'km=36000'))

    def test_descripcion_con_saltos_escritos(self):
        id_ = self.nuevo('Saltos', completo=False)
        self.ok('editar', id_, 'descripcion=Primer párrafo.\\n\\nSegundo párrafo.')
        self.assertEqual(self.json_de(id_)['descripcion'], 'Primer párrafo.\n\nSegundo párrafo.')

    def test_textos_peligrosos_quedan_como_texto(self):
        id_ = self.nuevo('Raro', fotos=5)
        texto = "<script>alert(1)</script> $(id) `id` ; rm -rf / \"comillas\" 'simples' 🚗🔥"
        self.ok('editar', id_, f'descripcion={texto}')
        self.assertEqual(self.json_de(id_)['descripcion'], texto)
        self.ok('publicar', id_)
        self.assertIn(texto, [a.get('descripcion') for a in self.publicados()])   # inventario.js sigue siendo JSON

    def test_valores_invalidos(self):
        id_ = self.nuevo('Invalido', completo=False)
        for campo in ('precio=abc', 'km=-5', 'historial.mantenimientos=Al día', 'anio=1850', 'colorx=rojo'):
            self.falla('editar', id_, campo)
        self.falla('editar', id_, 'descripcion=' + 'Muy bien cuidado. ' * 300)    # más de 4.000 caracteres
        # La placa completa no se rechaza: por privacidad se guarda solo el último dígito.
        self.assertIn('privacidad', self.ok('editar', id_, 'placa_fin=ABC123'))
        self.assertEqual(str(self.json_de(id_)['placa_fin']), '3')

    def test_limites_de_fotos(self):
        id_ = self.nuevo('Fotos', completo=False)
        self.assertIn('20', self.falla('foto', 'agregar', id_, *self.fotos[:21]))
        self.falla('foto', 'agregar', id_, str(self.falsa))
        self.falla('publicar', id_)                                                 # le faltan datos y fotos

    def test_permisos_del_vendedor(self):
        ajeno = self.nuevo('Ajeno', fotos=5)
        self.ok('publicar', ajeno)
        self.falla('vender', ajeno, '--confirmar', por=VENDEDOR)
        self.falla('editar', ajeno, 'precio=1', por=VENDEDOR)
        self.falla('destacar', ajeno, por=VENDEDOR)
        propio = self.nuevo('Propio', por=VENDEDOR, completo=False)
        self.ok('editar', propio, 'km=1000', por=VENDEDOR)


@unittest.skipIf(bool(LANZADOR), 'sin candado real no hay prueba de estrés')
class Estres(Base):
    def correr_muchos(self, ordenes, hilos):
        def una(args_por):
            args, por = args_por
            inicio = time.perf_counter()
            rc, salida = self.cat(*args, por=por)
            return rc, (time.perf_counter() - inicio) * 1000, salida
        with ThreadPoolExecutor(hilos) as ex:
            return list(ex.map(una, ordenes))

    def informe(self, nombre, resultados):
        tiempos = sorted(t for _, t, _ in resultados)
        p95 = tiempos[int(0.95 * (len(tiempos) - 1))]
        print(f'\n  {nombre}: {len(resultados)} cambios · fallaron {sum(rc != 0 for rc, _, _ in resultados)} · '
              f'mediana {statistics.median(tiempos):.0f} ms · p95 {p95:.0f} ms · máx {tiempos[-1]:.0f} ms')

    def test_tres_personas_a_la_vez(self):
        autos = {por: self.nuevo(f'Persona{por}', fotos=5) for por in (ANA, BETO, CARO)}
        antes = self.commits()
        ordenes = [(('editar', autos[por], f'km={10000 + i}'), por) for i in range(10) for por in autos]
        resultados = self.correr_muchos(ordenes, hilos=3)
        self.informe('3 personas × 10 cambios', resultados)
        self.assertTrue(all(rc == 0 for rc, _, _ in resultados), [s for rc, _, s in resultados if rc][:3])
        self.assertEqual(self.commits() - antes, 30)
        self.integridad()

    def test_rafaga_al_mismo_auto(self):
        id_ = self.nuevo('Rafaga', fotos=5)
        antes = self.commits()
        valores = [20000 + i for i in range(30)]
        resultados = self.correr_muchos([(('editar', id_, f'km={v}'), ANA) for v in valores], hilos=30)
        self.informe('30 cambios simultáneos al mismo auto', resultados)
        self.assertTrue(all(rc == 0 for rc, _, _ in resultados), [s for rc, _, s in resultados if rc][:3])
        self.assertIn(self.json_de(id_)['km'], valores)
        self.assertEqual(self.commits() - antes, 30)
        self.integridad()

    def test_flujos_completos_en_paralelo(self):
        def flujo(por):
            id_ = self.nuevo(f'Flujo{por}', por=por, fotos=5)
            for args in (('publicar', id_), ('vender', id_, '--confirmar'), ('reactivar', id_, 'km=1', 'precio=1 millón')):
                self.ok(*args, por=por)
            return id_
        with ThreadPoolExecutor(3) as ex:
            ids = list(ex.map(flujo, (ANA, BETO, CARO)))
        disponibles = {a['id'] for a in self.publicados() if a.get('estado', 'disponible') == 'disponible'}
        self.assertTrue(set(ids) <= disponibles)
        self.integridad()

    def test_candado_retenido(self):
        """Si otro proceso retiene el candado más de 30 s, el cambio avisa que está ocupado en vez de colgarse.
        (Las fotos y los videos se procesan antes de tomar el candado: solo el guardado lo ocupa.)"""
        id_ = self.nuevo('Candado', completo=False)
        (self.datos / '.candado').touch()
        bloqueo = subprocess.Popen([sys.executable, '-c', (
            'import fcntl, sys, time\n'
            'f = open(sys.argv[1], "a"); fcntl.flock(f, fcntl.LOCK_EX); print("tomado", flush=True); time.sleep(40)'),
            str(self.datos / '.candado')], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(bloqueo.stdout.readline().strip(), 'tomado')
            inicio = time.perf_counter()
            salida = self.falla('editar', id_, 'km=5')
            espera = time.perf_counter() - inicio
            print(f'\n  candado tomado: el cambio esperó {espera:.1f} s y respondió: {salida.strip()[:90]}')
            self.assertIn('ocupado', salida)
            self.assertGreater(espera, 25)
        finally:
            bloqueo.kill()
            bloqueo.wait()
        self.ok('editar', id_, 'km=6')               # al soltarse, todo sigue normal

    def commits(self):
        r = subprocess.run(['git', '-C', str(self.datos), 'rev-list', '--count', 'HEAD'], capture_output=True, text=True)
        return int(r.stdout.strip())


if __name__ == '__main__':
    unittest.main()
