"""Verify pure EPEVER decoding and bounded sensor snapshot publication."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from polstation.config import load_config
from polstation.sensors.preview import _decode_epever, run_sensor_preview, sensor_snapshot


ROOT = Path(__file__).resolve().parents[1]


class SensorPreviewTests(unittest.TestCase):
    def test_epever_register_decoding(self):
        values = _decode_epever(
            [607, 0, 0, 0, 1301, 0, 0, 0],
            [1301, 75, 975, 0, 1966, 2025],
            [68, 0],
            [0, 1, 1],
            [629, 0, 1303, 1300, 0, 0, 1, 0, 1, 0, 1, 0,
             0, 0, 0, 0, 0, 0, 0, 0],
            [1301, 0xFFB2, 0xFFFF],
        )
        self.assertEqual(values["pv_voltage_v"], 6.07)
        self.assertEqual(values["load_power_w"], 9.75)
        self.assertEqual(values["battery_soc_percent"], 68)
        self.assertEqual(values["battery_net_current_a"], -0.78)
        self.assertEqual(values["battery_voltage_state"], "normal")
        self.assertEqual(values["charging_stage"], "not charging")
        self.assertTrue(values["controller_running"])
        self.assertFalse(values["controller_fault"])
        self.assertEqual(values["consumed_total_kwh"], 0.01)

    def test_snapshot_keeps_sensor_failures_explicit(self):
        config = load_config(ROOT / "config/default.yaml")

        def good(_settings):
            return {"temperature_c": 18.2}

        def bad(_settings):
            raise OSError("adapter disconnected")

        with patch("polstation.sensors.preview.logger"):
            snapshot = sensor_snapshot(config, {"bme280": good, "epever": bad})
        self.assertEqual(snapshot["sensors"]["bme280"]["state"], "live")
        self.assertEqual(snapshot["sensors"]["epever"]["state"], "unavailable")
        self.assertIn("adapter disconnected", snapshot["sensors"]["epever"]["error"])
        self.assertEqual(snapshot["sensors"]["epever"]["values"], {})

    def test_publisher_replaces_one_bounded_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(ROOT / "config/default.yaml")
            config["storage"]["data_root"] = str(Path(directory) / "data")
            config["storage"]["state_root"] = str(Path(directory) / "state")

            class StopAfterOne:
                stopped = False

                def is_set(self):
                    return self.stopped

                def wait(self, _seconds):
                    self.stopped = True

            samplers = {
                "bme280": lambda _: {"temperature_c": 18.2},
                "epever": lambda _: {"pv_power_w": 0.0},
            }
            run_sensor_preview(config, StopAfterOne(), interval=0.01, samplers=samplers)
            path = Path(config["storage"]["state_root"]) / "sensor-preview.json"
            snapshot = json.loads(path.read_text())
            self.assertEqual(snapshot["mode"], "hardware-sensors")
            self.assertEqual(set(snapshot["sensors"]), {"bme280", "epever"})


if __name__ == "__main__":
    unittest.main()
