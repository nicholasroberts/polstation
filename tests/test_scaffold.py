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
