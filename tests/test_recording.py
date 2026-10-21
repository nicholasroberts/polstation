"""Verify immutable timed-observation bundles without camera hardware."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from polstation.acquisition.recording import (
    ObservationCaptureError,
    _next_exposure,
    exposure_timeout_ms,
    next_utc_slot,
    record_observation,
    run,
)
from polstation.config import load_config


ROOT = Path(__file__).resolve().parents[1]


class RecordingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.config = load_config(ROOT / "config/default.yaml")
        self.config["storage"]["data_root"] = str(root / "data")
        self.config["storage"]["state_root"] = str(root / "state")
        self.config["observation_capture"]["maximum_capture_attempts"] = 2
        self.config["observation_capture"]["stream_bytes_per_second"] = 30_000_000
        (root / "state").mkdir()
        (root / "state" / "sensor-preview.json").write_text(json.dumps({
            "mode": "hardware-sensors",
            "updated_at_utc": "2026-10-19T10:00:00+00:00",
            "sensors": {"bme280": {"state": "live"}},
        }))
        self.payloads = {
            camera["id"]: struct.pack("<16H", *([100 + index] * 16))
            for index, camera in enumerate(self.config["cameras"])
        }
        self.timestamps = iter([
            datetime(2026, 10, 19, 10, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 19, 10, 0, 1, tzinfo=timezone.utc),
        ])

    def capture(self, exposure_us, timeout_ms, attempt_number):
        frames = []
        for index, camera in enumerate(self.config["cameras"]):
            frames.append({
                "camera_id": camera["id"],
                "status": (
                    "incomplete" if attempt_number == 1 and index == 1 else "complete"
                ),
                "pixel_format": "Mono12",
                "width": 4,
                "height": 4,
                "exposure_readback_us": exposure_us,
                "raw": self.payloads[camera["id"]],
            })
        return {"request_span_ms": 0.8, "frames": frames}

    def test_complete_bundle_preserves_attempts_and_publishes_manifest_last(self):
        result = record_observation(
            self.config,
            self.capture,
            15_000,
            observation_id="obs-test",
            now=lambda: next(self.timestamps),
        )
        observation = result["path"]
        self.assertTrue((observation / "manifest.json").is_file())
        self.assertFalse((observation / "failure.json").exists())
        raw_files = sorted((observation / "raw").glob("*.raw"))
        self.assertEqual(len(raw_files), 6)
        manifest = json.loads((observation / "manifest.json").read_text())
        self.assertTrue(manifest["complete"])
        self.assertEqual(manifest["capture"]["selected_attempt"], 2)
        self.assertEqual(manifest["synchronization"], "software-parallel-unverified")
        self.assertEqual(manifest["raw_format"]["pixel_format"], "Mono12")
        self.assertFalse(manifest["exposure_control"]["validated_for_scientific_use"])
        self.assertEqual(manifest["sensor_snapshot"]["state"], "available")
        selected = manifest["capture"]["frames"][0]
        payload = self.payloads[selected["camera_id"]]
        self.assertEqual((observation / selected["relative_path"]).read_bytes(), payload)
        self.assertEqual(selected["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(
            manifest["config_snapshot"]["sha256"],
            hashlib.sha256((observation / "config.json").read_bytes()).hexdigest(),
        )
        with self.assertRaises(FileExistsError):
            record_observation(
                self.config, self.capture, 15_000,
                observation_id="obs-test",
                now=lambda: datetime(2026, 10, 19, 10, 0, 0, tzinfo=timezone.utc),
            )

    def test_failed_bundle_keeps_all_raw_attempts_without_manifest(self):
        def incomplete(exposure_us, timeout_ms, attempt_number):
            result = self.capture(exposure_us, timeout_ms, attempt_number)
            for frame in result["frames"]:
                frame["status"] = "incomplete"
            return result

        with self.assertRaises(ObservationCaptureError) as caught:
            record_observation(
                self.config,
                incomplete,
                120_000_000,
                observation_id="obs-failed",
                now=lambda: next(self.timestamps),
            )
        observation = caught.exception.path
        self.assertFalse((observation / "manifest.json").exists())
        self.assertEqual(len(list((observation / "raw").glob("*.raw"))), 6)
        failure = json.loads((observation / "failure.json").read_text())
        self.assertFalse(failure["complete"])
        self.assertEqual(failure["timeout_ms"], 130_000)
        self.assertEqual(len(failure["attempts"]), 2)

    def test_schedule_timeout_and_shared_auto_are_bounded(self):
        now = datetime(2026, 10, 19, 10, 3, 5, tzinfo=timezone.utc)
        self.assertEqual(
            next_utc_slot(now, 600),
            datetime(2026, 10, 19, 10, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(exposure_timeout_ms(120_000_000, 10), 130_000)
        settings = dict(self.config["observation_capture"], exposure_mode="shared_auto")
        self.assertEqual(_next_exposure(15_000, 2880, settings), 15_000)
        self.assertEqual(_next_exposure(15_000, 0, settings), 30_000)
        self.assertEqual(_next_exposure(120_000_000, 0, settings), 120_000_000)

    def test_once_run_publishes_completed_recorder_state(self):
        capture = self.capture
        for camera, angle in zip(self.config["cameras"], (0, 45, 90)):
            camera["polarizer_angle_deg"] = angle
            camera["preview_relative_gain"] = 1.0
        self.config["provenance"]["calibration_id"] = "test-relative-gains"

        class FakeRecorder:
            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return None

            def capture_attempt(self, exposure_us, timeout_ms, attempt_number):
                return capture(exposure_us, timeout_ms, attempt_number)

        with patch("polstation.acquisition.recording.free_bytes", return_value=10**12):
            run(
                self.config,
                threading.Event(),
                once=True,
                recorder_factory=lambda config: FakeRecorder(),
            )
        state_path = Path(self.config["storage"]["state_root"]) / "observation-recorder.json"
        state = json.loads(state_path.read_text())
        self.assertEqual(state["state"], "complete")
        self.assertEqual(state["last_attempt_state"], "complete")
        self.assertIsNone(state["last_error"])
        self.assertIsNotNone(state["last_acquisition_at_utc"])
        observation = Path(self.config["storage"]["data_root"]) / state[
            "last_observation_relative_path"
        ]
        self.assertTrue((observation / "manifest.json").is_file())
        preview = json.loads(
            (Path(self.config["storage"]["state_root"]) /
             "observation-preview.json").read_text()
        )
        self.assertEqual(preview["mode"], "recorded-observation-preview")
        self.assertEqual(preview["observation_id"], state["last_observation_id"])
        self.assertTrue(preview["diagnostic_only"])
        self.assertTrue(preview["raw_files_unchanged"])
        self.assertEqual(
            [camera["state"] for camera in preview["cameras"]],
            ["recorded", "recorded", "recorded"],
        )
        self.assertTrue(all(camera["preview_png"] for camera in preview["cameras"]))
        self.assertEqual(preview["polarization"]["state"], "recorded")
        self.assertEqual(
            preview["polarization"]["source_observation_id"],
            state["last_observation_id"],
        )


if __name__ == "__main__":
    unittest.main()
