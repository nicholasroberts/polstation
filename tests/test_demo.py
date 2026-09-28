"""Check preview isolation, fault semantics and the actual HTTP boundary."""
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from polstation.cameras.demo import DemoPreviewSource
from polstation.cameras.preview import FilePreviewSource, mono8_preview_png
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
            page = response.read().decode()
            self.assertIn('DEMO — no cameras connected', page)
            self.assertIn('Remote SkyPolStation', page)
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

    def test_mono8_preview_is_bounded_png(self):
        image = mono8_preview_png(bytes(range(24)), 6, 4, max_width=3, max_height=2)
        self.assertEqual(image[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', image[16:24]), (3, 2))

    def test_file_preview_source_reads_latest_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            self.config['storage']['state_root'] = directory
            source = FilePreviewSource(self.config)
            self.assertFalse(source.snapshot()['hardware_ready'])
            value = {'mode': 'hardware-preview', 'hardware_ready': True, 'recording': False,
                     'synchronization': 'unverified', 'cameras': [{
                         'id': 'camera', 'state': 'live',
                         'captured_at_utc': '2000-01-01T00:00:00+00:00'}]}
            (Path(directory) / 'camera-previews.json').write_text(json.dumps(value))
            snapshot = source.snapshot()
            self.assertFalse(snapshot['hardware_ready'])
            self.assertGreater(snapshot['cameras'][0]['age_seconds'], 0)
            self.assertEqual(snapshot['cameras'][0]['state'], 'stale')
            with self.assertRaises(ValueError):
                source.snapshot('faults')
