import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
from http.server import ThreadingHTTPServer

from polstation.acquisition.service import run
from polstation.config import load_config
from polstation.health.status import read
from polstation.storage.manifests import write_json, config_digest
from polstation.web.app import make_handler

ROOT = Path(__file__).resolve().parents[1]


class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = load_config(ROOT / "config/default.yaml")
        for key in ("data_root", "state_root"):
            self.config["storage"][key] = str(Path(self.tmp.name) / key)

    def test_examples_and_validation(self):
        import yaml
        load_config(ROOT / "config/example_field_config.yaml")
        legacy = copy.deepcopy(self.config)
        legacy.pop("camera_preview")
        for camera in legacy["cameras"]:
            camera.pop("preview_relative_gain")
        legacy_path = Path(self.tmp.name) / "legacy.yaml"
        legacy_path.write_text(yaml.safe_dump(legacy))
        self.assertEqual(load_config(legacy_path)["camera_preview"]["exposure_mode"],
                         "shared_auto")
        self.assertTrue(all(camera["preview_relative_gain"] is None
                            for camera in load_config(legacy_path)["cameras"]))
        for section, key, value in [("dashboard", "host", "0.0.0.0"),
                                    ("dashboard", "port", True),
                                    ("acquisition", "heartbeat_seconds", 0),
                                    ("acquisition", "retry_max_seconds", float("nan"))]:
            config = copy.deepcopy(self.config)
            config[section][key] = value
            path = Path(self.tmp.name) / "bad.yaml"
            path.write_text(yaml.safe_dump(config))
            with self.assertRaises(ValueError):
                load_config(path)

        for angles in ([0, 45, None], [0, 45, 135], [False, 45, 90]):
            config = copy.deepcopy(self.config)
            for camera, angle in zip(config["cameras"], angles):
                camera["polarizer_angle_deg"] = angle
            path = Path(self.tmp.name) / "bad-angles.yaml"
            path.write_text(yaml.safe_dump(config))
            with self.assertRaisesRegex(ValueError, "polarizer angles"):
                load_config(path)

        config = copy.deepcopy(self.config)
        config["cameras"][0]["preview_relative_gain"] = 1.1
        path = Path(self.tmp.name) / "partial-gains.yaml"
        path.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(ValueError, "all three cameras"):
            load_config(path)

        config = copy.deepcopy(self.config)
        for camera, gain in zip(config["cameras"], (1.5, 1.0, 0.98)):
            camera["preview_relative_gain"] = gain
        path = Path(self.tmp.name) / "unidentified-gains.yaml"
        path.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(ValueError, "calibration_id"):
            load_config(path)
        config["provenance"]["calibration_id"] = "preview-relative-response-test"
        path.write_text(yaml.safe_dump(config))
        self.assertEqual(load_config(path)["cameras"][0]["preview_relative_gain"], 1.5)

        config = copy.deepcopy(self.config)
        camera_ids = [camera["id"] for camera in config["cameras"]]
        config["provenance"]["calibration_id"] = "instrument-matrix-test"
        config["polarization_preview"]["instrument_matrix"] = {
            "camera_order": camera_ids,
            "response_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            "sensor_aop_offset_deg": 90,
            "dark_model": {
                "exposure_ms": [15, 30],
                "roi_median_mono12_by_camera": {
                    camera_id: [20, 22] for camera_id in camera_ids
                },
                "mono12_to_mono8_divisor": 16,
            },
        }
        path = Path(self.tmp.name) / "instrument-matrix.yaml"
        path.write_text(yaml.safe_dump(config))
        self.assertEqual(
            load_config(path)["polarization_preview"]["instrument_matrix"]["sensor_aop_offset_deg"],
            90,
        )
        config["polarization_preview"]["instrument_matrix"]["response_matrix"][1] = [1, 0, 0]
        path.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(ValueError, "nonsingular"):
            load_config(path)

        config = copy.deepcopy(self.config)
        config["sensors"]["bme280"].update({"bus": 1, "address": None})
        path = Path(self.tmp.name) / "bad-bme280.yaml"
        path.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(ValueError, "BME280 address"):
            load_config(path)

        config = copy.deepcopy(self.config)
        config["sensors"]["epever"]["device"] = "/dev/ttyACM0"
        path = Path(self.tmp.name) / "bad-epever.yaml"
        path.write_text(yaml.safe_dump(config))
        with self.assertRaisesRegex(ValueError, "configured together"):
            load_config(path)

    def test_no_observations_and_provenance(self):
        run(self.config, threading.Event(), once=True)
        status = read(self.config)
        self.assertEqual(status["state"], "scaffold_idle")
        self.assertFalse(status["hardware_ready"])
        self.assertFalse(status["stale"])
        self.assertEqual(status["config_sha256"], config_digest(self.config))
        self.assertEqual(list(Path(self.config["storage"]["data_root"]).iterdir()), [])

    def test_low_disk_preserves_files(self):
        data = Path(self.config["storage"]["data_root"])
        data.mkdir()
        (data / "raw.bin").write_bytes(b"untouched")
        with patch("polstation.acquisition.service.free_bytes", return_value=0):
            run(self.config, threading.Event(), once=True)
        self.assertEqual(read(self.config)["state"], "low_disk")
        self.assertEqual((data / "raw.bin").read_bytes(), b"untouched")

    def test_atomic_no_overwrite_and_cleanup(self):
        path = Path(self.tmp.name) / "manifest.json"
        write_json(path, {"original": True})
        with self.assertRaises(FileExistsError):
            write_json(path, {"original": False})
        self.assertEqual(json.loads(path.read_text()), {"original": True})
        with patch("polstation.storage.manifests.os.replace", side_effect=OSError("failure")):
            with self.assertRaises(OSError):
                write_json(path, {}, replace=True)
        self.assertEqual(list(path.parent.glob(".pending-*")), [])
        self.assertEqual(json.loads(path.read_text()), {"original": True})

    def test_retry_is_capped_and_stoppable(self):
        class Stop:
            waits = []
            def is_set(self):
                return len(self.waits) >= 8
            def wait(self, seconds):
                self.waits.append(seconds)
        stop = Stop()
        with patch("polstation.acquisition.service.prepare", side_effect=OSError("offline")), patch("polstation.acquisition.service.publish"), patch("polstation.acquisition.service.logger"):
            run(self.config, stop)
        self.assertEqual(stop.waits, [1, 2, 4, 8, 16, 32, 60, 60])

    def test_stale_missing_and_corrupt_health(self):
        self.assertTrue(read(self.config)["stale"])
        run(self.config, threading.Event(), once=True)
        path = Path(self.config["storage"]["state_root"]) / "health.json"
        value = json.loads(path.read_text())
        value["updated_at_utc"] = "2000-01-01T00:00:00+00:00"
        path.write_text(json.dumps(value))
        self.assertTrue(read(self.config)["stale"])
        path.write_text("broken")
        self.assertTrue(read(self.config)["stale"])

    def test_http_status_and_shutdown(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.config))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}"
            with urlopen(url) as response:
                self.assertIn(b"Scaffold mode", response.read())
            with self.assertRaises(HTTPError) as caught:
                urlopen(url + "/api/status")
            self.assertEqual(caught.exception.code, 503)
            caught.exception.close()
            run(self.config, threading.Event(), once=True)
            with urlopen(url + "/api/status") as response:
                self.assertEqual(response.status, 200)
            stop = threading.Event()
            stop.set()
            run(self.config, stop)
            self.assertEqual(read(self.config)["state"], "stopped")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
