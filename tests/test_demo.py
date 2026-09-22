"""Check preview isolation, fault semantics and the actual HTTP boundary."""
import json
from pathlib import Path
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from polstation.cameras.demo import DemoPreviewSource
from polstation.config import load_config
from polstation.web.app import make_handler


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(Path(__file__).resolve().parents[1] / 'config/default.yaml')
        self.now = 100.0
        self.source = DemoPreviewSource(self.config['cameras'], clock=lambda: self.now, wall_clock=lambda: 1700000000)

    def test_frames_advance_and_fault_frame_is_frozen(self):
        first = self.source.snapshot()
        self.now += 10
        second = self.source.snapshot()
        self.assertEqual(len(second['cameras']), 3)
        self.assertFalse(second['recording'])
        self.assertFalse(second['hardware_ready'])
        for before, after in zip(first['cameras'], second['cameras']):
            self.assertNotEqual(before['preview_svg'], after['preview_svg'])
            self.assertEqual(after['frame_number'], 11)
            self.assertIn('SIMULATED', after['preview_svg'])
        fault = self.source.snapshot('faults')
        self.now += 20
        later = self.source.snapshot('faults')
        self.assertEqual([c['state'] for c in fault['cameras']], ['live', 'stale', 'disconnected'])
        self.assertEqual(fault['cameras'][1]['preview_svg'], later['cameras'][1]['preview_svg'])
        self.assertEqual(later['cameras'][1]['age_seconds'], 60)
        self.assertIsNone(later['cameras'][2]['preview_svg'])
        self.assertIsNone(later['cameras'][2]['captured_at_utc'])
        self.assertEqual(self.source.snapshot()['cameras'][1]['state'], 'live')

    def test_escape_camera_identity(self):
        self.config['cameras'][0]['id'] = '<script>bad</script>'
        svg = self.source.snapshot()['cameras'][0]['preview_svg']
        self.assertNotIn('<script>', svg)
        self.assertIn('&lt;script&gt;', svg)

    def start_server(self, source):
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.config, source))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join()
        self.addCleanup(close)
        return f'http://127.0.0.1:{server.server_port}'

    def test_demo_api_and_assets(self):
        base = self.start_server(self.source)
        with urlopen(base) as response:
            self.assertIn('DEMO — no cameras connected', response.read().decode())
        for asset in ('dashboard.css', 'dashboard.js'):
            with urlopen(base + '/static/' + asset) as response:
                self.assertEqual(response.status, 200)
        with urlopen(base + '/api/previews?scenario=faults') as response:
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(json.load(response)['cameras'][2]['state'], 'disconnected')
        for path, expected in [('/api/previews?scenario=invalid', 400), ('/static/../app.py', 404)]:
            with self.assertRaises(HTTPError) as caught:
                urlopen(base + path)
            self.assertEqual(caught.exception.code, expected)
            caught.exception.close()

    def test_demo_is_opt_in(self):
        base = self.start_server(None)
        with self.assertRaises(HTTPError) as caught:
            urlopen(base + '/api/previews')
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()
