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
from polstation.cameras.preview import (
    FilePreviewSource,
    _focus_metric,
    _next_shared_exposure,
    _percentile_dn,
    _polarization_snapshot,
    mono8_preview_png,
)
from polstation.polarization.preview import central_circular_roi
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
        self.assertIn('Environment and power', page)
        self.assertIn('ROI focus', page)
        assets = {}
        for asset in ('dashboard.css', 'dashboard.js'):
            with urlopen(base + '/static/' + asset) as response:
                self.assertEqual(response.status, 200)
                assets[asset] = response.read().decode()
        self.assertIn('Central circular ROI only · outside masked', assets['dashboard.js'])
        self.assertIn("camera.focus_metric", assets['dashboard.js'])
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

    def test_preview_brightness_percentile_uses_nearest_rank(self):
        self.assertEqual(_percentile_dn(bytes([0, 10, 20, 255]), 50), 10)
        self.assertEqual(_percentile_dn(bytes([0, 10, 20, 255]), 99), 255)

    def test_shared_auto_exposure_is_bounded_and_holds_within_tolerance(self):
        settings = self.config['camera_preview']
        self.assertEqual(_next_shared_exposure(15000, 180, settings), 15000)
        self.assertEqual(_next_shared_exposure(15000, 255, settings), 7500)
        self.assertEqual(_next_shared_exposure(15000, 0, settings), 30000)
        self.assertEqual(_next_shared_exposure(100, 255, settings), 100)
        self.assertEqual(_next_shared_exposure(500000, 0, settings), 500000)

    def test_focus_metric_uses_only_central_circular_roi(self):
        width = height = 9
        mask, _ = central_circular_roi(width, height)
        flat = bytes([50] * (width * height))
        patterned = bytearray(flat)
        for y in range(height):
            for x in range(width):
                if mask[y * width + x]:
                    patterned[y * width + x] = 0 if (x + y) % 2 else 100
        outside_changed = bytearray(flat)
        for index, inside in enumerate(mask):
            if not inside:
                outside_changed[index] = 0 if index % 2 else 255
        self.assertEqual(_focus_metric(flat, width, height, mask), 0.0)
        self.assertGreater(_focus_metric(patterned, width, height, mask), 0.0)
        self.assertEqual(_focus_metric(outside_changed, width, height, mask), 0.0)

    def test_polarization_snapshot_reports_relative_sensitivity_normalization(self):
        gains = (2.0, 1.0, 1.0)
        sampled = {}
        for camera, angle, gain, pixels in zip(
                self.config["cameras"], (0, 45, 90), gains,
                (bytes([50]), bytes([100]), bytes([100]))):
            camera["polarizer_angle_deg"] = angle
            camera["preview_relative_gain"] = gain
            sampled[camera["id"]] = (1, 1, pixels)
        self.config["provenance"]["calibration_id"] = "relative-test"

        result = _polarization_snapshot(self.config, sampled)

        self.assertEqual(result["state"], "live")
        self.assertTrue(result["relative_sensitivity_corrected"])
        self.assertFalse(result["dark_corrected"])
        self.assertFalse(result["calibrated"])
        self.assertEqual(result["calibration_id"], "relative-test")
        self.assertEqual(result["relative_gains_by_angle"], {0: 2.0, 45: 1.0, 90: 1.0})

    def test_polarization_snapshot_reports_provisional_instrument_matrix(self):
        sampled = {}
        pixels = (bytes([110]), bytes([10]), bytes([110]))
        for camera, angle, channel in zip(self.config["cameras"], (0, 45, 90), pixels):
            camera["polarizer_angle_deg"] = angle
            sampled[camera["id"]] = (1, 1, channel)
        camera_ids = [camera["id"] for camera in self.config["cameras"]]
        self.config["provenance"]["calibration_id"] = "matrix-test"
        self.config["polarization_preview"]["instrument_matrix"] = {
            "camera_order": camera_ids,
            "response_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "sensor_aop_offset_deg": 90,
            "dark_model": {
                "exposure_ms": [15, 30],
                "roi_median_mono12_by_camera": {
                    camera_id: [160, 160] for camera_id in camera_ids
                },
                "mono12_to_mono8_divisor": 16,
            },
        }

        result = _polarization_snapshot(self.config, sampled, 20000)

        self.assertEqual(result["state"], "live")
        self.assertEqual(result["correction_method"], "provisional_instrument_matrix")
        self.assertTrue(result["scalar_dark_offset_corrected"])
        self.assertFalse(result["dark_corrected"])
        self.assertFalse(result["calibrated"])
        self.assertIsNone(result["relative_gains_by_angle"])
        self.assertFalse(result["scalar_relative_gains_applied"])
        self.assertEqual(result["scalar_dark_offsets_dn"], dict.fromkeys(camera_ids, 10.0))
        self.assertEqual(result["matrix_valid_exposure_ms"], [15, 30])

        unavailable = _polarization_snapshot(self.config, sampled, 1000)
        self.assertEqual(unavailable["state"], "unavailable")
        self.assertEqual(unavailable["correction_method"], "provisional_instrument_matrix")
        self.assertIn("valid only from 15 to 30 ms", unavailable["error"])

    def test_instrument_matrix_holds_first_dark_offset_below_measured_range(self):
        sampled = {}
        pixels = (bytes([110]), bytes([10]), bytes([110]))
        for camera, angle, channel in zip(self.config["cameras"], (0, 45, 90), pixels):
            camera["polarizer_angle_deg"] = angle
            sampled[camera["id"]] = (1, 1, channel)
        camera_ids = [camera["id"] for camera in self.config["cameras"]]
        self.config["provenance"]["calibration_id"] = "low-exposure-matrix-test"
        self.config["polarization_preview"]["instrument_matrix"] = {
            "camera_order": camera_ids,
            "response_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "sensor_aop_offset_deg": 90,
            "dark_model": {
                "exposure_ms": [1, 5],
                "roi_median_mono12_by_camera": {
                    camera_id: [16, 32] for camera_id in camera_ids
                },
                "mono12_to_mono8_divisor": 16,
                "minimum_supported_exposure_ms": 0.1,
                "below_measured_policy": "hold_first_offset",
            },
        }

        result = _polarization_snapshot(self.config, sampled, 500)

        self.assertEqual(result["state"], "live")
        self.assertEqual(result["scalar_dark_offsets_dn"], dict.fromkeys(camera_ids, 1.0))
        self.assertEqual(result["matrix_valid_exposure_ms"], [0.1, 5])
        self.assertEqual(result["matrix_measured_dark_exposure_ms"], [1, 5])
        self.assertEqual(result["matrix_low_exposure_dark_policy"], "hold_first_offset")

        unavailable = _polarization_snapshot(self.config, sampled, 50)
        self.assertEqual(unavailable["state"], "unavailable")
        self.assertIn("valid only from 0.1 to 5 ms", unavailable["error"])

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
            sensors = {'mode': 'hardware-sensors', 'sensors': {
                'bme280': {'state': 'live', 'sampled_at_utc': '2000-01-01T00:00:00+00:00',
                           'values': {'temperature_c': 18.2}},
                'epever': {'state': 'unavailable', 'sampled_at_utc': None, 'values': {}}}}
            (Path(directory) / 'sensor-preview.json').write_text(json.dumps(sensors))
            snapshot = source.snapshot()
            self.assertFalse(snapshot['hardware_ready'])
            self.assertGreater(snapshot['cameras'][0]['age_seconds'], 0)
            self.assertEqual(snapshot['cameras'][0]['state'], 'stale')
            self.assertEqual(snapshot['sensors']['bme280']['state'], 'stale')
            self.assertEqual(snapshot['sensors']['epever']['state'], 'unavailable')
            with self.assertRaises(ValueError):
                source.snapshot('faults')
