"""Pruebas de la extensión del asistente (hermes/plugin/mendiautos), sin Hermes ni Telegram.

Cubren las confirmaciones con botones («Publicar», «Sí»), el texto que llega al chat (saltos de línea,
Markdown, razonamiento en inglés) y pruebas de estrés (texto aleatorio, muchos hilos a la vez).

    python -m unittest discover -s hermes/pruebas -v
"""
import json
import logging
import random
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin'))
import mendiautos as m  # noqa: E402

logging.getLogger(m.__name__).setLevel(logging.ERROR)   # sin los avisos de «quité N líneas» en las pruebas
ADMIN = {'id': '111', 'nombre': 'Prueba', 'rol': 'administrador'}
BS = chr(92)                     # barra invertida: «\n» escrito como texto es BS + 'n'
N_ESCRITO = BS + 'n'


def clarify(eleccion, status='answered'):
    """Lo que devuelve la herramienta clarify de Hermes cuando la persona toca un botón."""
    return json.dumps({'responses': [{'question': '¿Qué hacemos?', 'choices_offered': ['Publicar', 'Corregir algo'],
                                      'status': status,
                                      'user_response': eleccion if status == 'answered' else None}],
                       'outcome': 'submitted'}, ensure_ascii=False)


class Base(unittest.TestCase):
    """quien() y correr() simulados: nada sale del proceso."""

    def setUp(self):
        m._estado.clear()
        self.ordenes = []

        def correr(_comando, args, tiempo=120):
            self.ordenes.append(list(args))
            if args[0] == 'vender' and '--confirmar' not in args:
                return True, ('Para confirmar la venta, muéstrale esto a quien lo pidió:\n'
                              '  Kia Picanto · año 2021 · $42.000.000\n'
                              f'Si lo confirma: catalogo vender {args[1]} --confirmar')
            if args[:2] == ['foto', 'listar']:
                return True, ('Kia Picanto 2021: 2 fotos (la 1 es la portada)\n'
                              '  1. https://ejemplo.invalid/a.jpg\n'
                              '     archivo: /var/lib/mendiautos/catalogo/fotos/kia/a-m.jpg\n'
                              '  2. https://ejemplo.invalid/b.jpg\n'
                              '     archivo: /var/lib/mendiautos/catalogo/fotos/kia/b-m.jpg')
            if any(a.startswith('historial.mantenimientos=') and not a.split('=', 1)[1].isdigit() for a in args):
                return False, 'Error: Mantenimientos (historial.mantenimientos): debe ser un número entre 0 y 999.'
            if 'ocupado' in args:
                return False, 'Error: El catálogo está ocupado con otro cambio; intenta de nuevo en un momento.'
            return True, 'Hecho: ' + ' '.join(args)

        mock.patch.object(m, 'quien', return_value=(ADMIN, 'telegram')).start()
        mock.patch.object(m, 'correr', side_effect=correr).start()
        mock.patch.object(m, 'equipo', return_value={'111': ADMIN}).start()
        self.addCleanup(mock.patch.stopall)

    def mensaje(self, texto):
        """Llega un mensaje escrito por la persona (gancho pre_llm_call, una vez por turno)."""
        m.antes_de_llamar_al_modelo(user_message=texto, sender_id='111', platform='telegram')

    def boton(self, eleccion, status='answered'):
        """La persona toca un botón de una pregunta clarify (gancho post_tool_call)."""
        m.despues_de_herramienta(tool_name='clarify', result=clarify(eleccion, status))

    def catalogo(self, orden):
        return json.loads(m.herramienta_catalogo({'orden': orden}))


class ConfirmacionesConBotones(Base):
    def test_publicar_con_el_boton_basta_una_vez(self):
        self.mensaje('Cambia el kilometraje a 90 mil')
        self.assertFalse(self.catalogo('publicar kia-picanto-2021')['ok'])
        self.boton('Publicar')
        r = self.catalogo('publicar kia-picanto-2021')
        self.assertTrue(r['ok'], r)
        self.assertIn(['publicar', 'kia-picanto-2021', '--por', '111'], self.ordenes)
        # Un «Publicar» sirve para una sola publicación.
        self.assertFalse(self.catalogo('publicar kia-picanto-2021')['ok'])

    def test_publicar_escrito(self):
        self.mensaje('Publicar')
        self.assertTrue(self.catalogo('publicar kia-picanto-2021')['ok'])

    def test_no_publica_si_dice_que_no(self):
        for texto in ('no lo publiques todavía', '¿lo publico?', 'todavía no publicar'):
            self.mensaje(texto)
            self.assertFalse(self.catalogo('publicar kia-picanto-2021')['ok'], texto)

    def test_vender_con_el_boton_si(self):
        self.mensaje('✅ Marcar vendido')
        r = self.catalogo('vender kia-picanto-2021')
        self.assertTrue(r['ok'] and r.get('necesita_confirmacion'), r)
        self.boton('Sí')
        r = self.catalogo('vender kia-picanto-2021 --confirmar')
        self.assertTrue(r['ok'], r)
        self.assertIn('--confirmar', self.ordenes[-1])

    def test_vender_con_el_boton_no(self):
        self.mensaje('✅ Marcar vendido')
        self.catalogo('vender kia-picanto-2021')
        self.boton('No')
        self.assertFalse(self.catalogo('vender kia-picanto-2021 --confirmar')['ok'])

    def test_vender_sin_respuesta(self):
        self.mensaje('✅ Marcar vendido')
        self.catalogo('vender kia-picanto-2021')
        self.boton(None, status='unanswered')
        self.assertFalse(self.catalogo('vender kia-picanto-2021 --confirmar')['ok'])

    def test_vender_con_si_escrito(self):
        self.mensaje('se vendió el picanto')
        self.catalogo('vender kia-picanto-2021')
        self.mensaje('Sí, confirmo')
        self.assertTrue(self.catalogo('vender kia-picanto-2021 --confirmar')['ok'])

    def test_formato_viejo_y_etiqueta_recommended(self):
        self.assertEqual(m.eleccion_clarify('{"user_response": "Sí"}'), 'Sí')
        self.assertEqual(m.eleccion_clarify(clarify('Publicar (Recommended)')), 'Publicar')
        self.assertEqual(m.eleccion_clarify('no es json'), '')
        self.assertEqual(m.eleccion_clarify(clarify(None, 'unanswered')), '')


class TextoDeLasPreguntasConBotones(unittest.TestCase):
    PREGUNTA = ('🚗 **Resumen del Kia Picanto 2021**' + N_ESCRITO * 2 + '• Precio: $42.000.000' + N_ESCRITO +
                '• Vista previa: https://mendiautos.co/DetalleAuto.dc.html?previa=AbCdEfGhIjKlMnOpQrStUv' +
                N_ESCRITO * 2 + '¿Qué deseas hacer?')

    def test_saltos_reales_sin_markdown_y_enlace_limpio(self):
        cambios = m.limpiar_clarify({'questions': [{'question': self.PREGUNTA,
                                                    'choices': ['Publicar (Recommended)', 'Corregir algo']}]})
        q = cambios['questions'][0]
        self.assertNotIn(BS, q['question'])
        self.assertNotIn('**', q['question'])
        # El enlace termina en un salto de línea real: nada pegado que rompa la clave de la vista previa.
        self.assertIn('previa=AbCdEfGhIjKlMnOpQrStUv\n', q['question'])
        self.assertEqual(q['choices'], ['Publicar', 'Corregir algo'])

    def test_enlace_markdown(self):
        self.assertEqual(m.texto_plano('[Ver la ficha](https://mendiautos.co/x)'), 'Ver la ficha: https://mendiautos.co/x')

    def test_formato_antiguo_de_clarify(self):
        cambios = m.limpiar_clarify({'question': 'Uno' + N_ESCRITO + 'Dos', 'choices': ['Sí', 'No']})
        self.assertEqual(cambios, {'question': 'Uno\nDos'})

    def test_si_ya_esta_bien_no_cambia(self):
        self.assertIsNone(m.limpiar_clarify({'questions': [{'question': '¿Confirmas la venta?', 'choices': ['Sí', 'No']}]}))

    def test_gancho_antes_de_herramienta(self):
        self.assertEqual(m.antes_de_herramienta(tool_name='terminal', args={})['action'], 'block')
        self.assertEqual(m.antes_de_herramienta(tool_name='clarify', args={'questions': [{'question': self.PREGUNTA}]})
                         ['action'], 'modify')
        self.assertIsNone(m.antes_de_herramienta(tool_name='catalogo', args={'orden': 'listar'}))


class TextoDeLasRespuestas(unittest.TestCase):
    FUGA = ('`listar --vendidos` shows the sold cars (in this case, the Kia sold today).\n'
            "Let's format the response nicely for the user, following his preference. Wait, he asked: "
            '"Cuáles carros vendí este mes".\n'
            "Let's answer:\n"
            '1. 🛻 Kia Picanto 2021 (vendido el 3 de octubre de 2026)Aquí tienes el auto vendido este mes:\n\n'
            '1. 🛻 Kia Picanto 2021 — Vendido el 3 de octubre de 2026')

    def test_quita_el_razonamiento_en_ingles(self):
        limpio = m.limpiar_respuesta(response_text=self.FUGA)
        self.assertTrue(limpio.startswith('Aquí tienes el auto vendido este mes:'), limpio)
        self.assertFalse(any(m.es_ingles(l) for l in limpio.split('\n')), limpio)
        self.assertIn('1. 🛻 Kia Picanto 2021 — Vendido el 3 de octubre de 2026', limpio)

    def test_respuestas_en_espanol_no_cambian(self):
        for texto in (
            '¡Listo, Felipe! 🚗\nPrecio: $180.000.000 ✓',
            '1. 🚙 Mazda CX-30 Grand Touring 2024 — 6.200 km\n2. 🛻 Toyota Hilux SRV 2024 — 8.900 km',
            '¿Has visto la vista previa? He subido las 5 fotos 📸',
            '🏎️ Land Rover Range Rover Sport 2022 · Chevrolet Tracker Premier 2023 · Mini Cooper S 2020',
            'Show de precios este fin de semana: el Kia está en $42 millones.',
            'MEDIA:/var/lib/mendiautos/catalogo/fotos/kia/a-m.jpg',
        ):
            self.assertIsNone(m.limpiar_respuesta(response_text=texto), texto)

    def test_saltos_escritos(self):
        self.assertEqual(m.limpiar_respuesta(response_text='Listo ✓' + N_ESCRITO + 'Precio: $1 ✓'),
                         'Listo ✓\nPrecio: $1 ✓')

    def test_todo_en_ingles_no_deja_el_mensaje_vacio(self):
        self.assertIsNone(m.limpiar_respuesta(response_text="Let's check the list and then answer the user."))


class PistasParaElModelo(Base):
    def test_dato_rechazado_pide_preguntar_sin_inventar(self):
        r = self.catalogo('editar kia "historial.mantenimientos=Al día"')
        self.assertFalse(r['ok'])
        self.assertIn('No inventes', r['salida'])

    def test_catalogo_ocupado(self):
        r = self.catalogo('editar ocupado precio=1')
        self.assertFalse(r['ok'])
        self.assertIn('Espera un momento', r['salida'])

    def test_fotos_con_lineas_media(self):
        r = self.catalogo('foto listar kia')
        self.assertIn('MEDIA:/var/lib/mendiautos/catalogo/fotos/kia/a-m.jpg', r['salida'])
        self.assertIn('MEDIA:/var/lib/mendiautos/catalogo/fotos/kia/b-m.jpg', r['salida'])


class Estres(unittest.TestCase):
    PIEZAS = ['\\', 'n', 'r', '*', '**', '`', '_', '__', '~', '[', ']', '(', ')', ' ', '  ', '\n', '\t', '#', '-',
              'á', 'ñ', '¿', '?', '🚗', '✓', 'http://x.y/z', 'Precio', 'the', "let's", 'answer', 'Aquí', 'tienes',
              'auto', 'vendido', 'Recommended', '(Recommended)', 'MEDIA:/a/b.jpg', '.', ',', 'A', 'z', '0', '9']

    def aleatorio(self, rnd):
        return ''.join(rnd.choice(self.PIEZAS) for _ in range(rnd.randint(0, 60)))

    def test_texto_aleatorio(self):
        """20.000 textos al azar: nada falla, nunca queda un «\\n» escrito y limpiar dos veces da lo mismo."""
        rnd = random.Random(2026)
        for _ in range(20000):
            s = self.aleatorio(rnd)
            plano = m.texto_plano(s)
            self.assertNotIn(N_ESCRITO, plano, repr(s))
            self.assertEqual(m.texto_plano(plano), plano, repr(s))
            m.limpiar_clarify({'questions': [{'question': s, 'choices': [s[:40] or 'x', 'No']}]})
            r = m.limpiar_respuesta(response_text=s)
            if r is not None:
                self.assertNotIn(N_ESCRITO, r, repr(s))
                self.assertIsNone(m.limpiar_respuesta(response_text=r), repr(s))

    def test_muchos_hilos_a_la_vez(self):
        """32 hilos anotan mensajes de 8 personas al mismo tiempo: no se pierde ninguno."""
        m._estado.clear()
        por_hilo, hilos = 2500, 32

        def trabajo(i):
            for k in range(por_hilo):
                uid = f'u{(i + k) % 8}'
                m.anotar(uid, 'Publicar' if k % 2 else 'hola')
                m.estado(uid)

        ts = [threading.Thread(target=trabajo, args=(i,)) for i in range(hilos)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sum(e['turno'] for e in m._estado.values()), por_hilo * hilos)

    def test_rafaga_de_publicaciones(self):
        """200 personas piden publicar a la vez; solo publican las que dijeron «Publicar», y una vez cada una."""
        m._estado.clear()
        miembros = {str(i): {'id': str(i), 'nombre': f'P{i}', 'rol': 'administrador'} for i in range(200)}
        publicadas, candado = [], threading.Lock()
        local = threading.local()

        def correr(_c, args, tiempo=120):
            with candado:
                publicadas.append(args[-1])
            return True, 'Publicado'

        def trabajo(i):
            local.m = miembros[str(i)]
            m.anotar(str(i), 'Publicar' if i % 2 == 0 else 'Corregir algo')
            for _ in range(3):
                m.herramienta_catalogo({'orden': f'publicar auto-{i}'})

        with mock.patch.object(m, 'quien', side_effect=lambda: (local.m, 'telegram')), \
                mock.patch.object(m, 'correr', side_effect=correr):
            ts = [threading.Thread(target=trabajo, args=(i,)) for i in range(200)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(sorted(publicadas, key=int), [str(i) for i in range(0, 200, 2)])

    def test_rendimiento(self):
        """Limpiar una respuesta larga (4.000 caracteres) toma menos de 2 ms en promedio."""
        texto = ('1. 🚙 Mazda CX-30 Grand Touring 2024 — 6.200 km ✓' + N_ESCRITO) * 80
        inicio = time.perf_counter()
        for _ in range(500):
            m.limpiar_respuesta(response_text=texto)
        self.assertLess((time.perf_counter() - inicio) / 500, 0.002)


if __name__ == '__main__':
    unittest.main()
