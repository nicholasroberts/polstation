"""Verify bounded dashboard summaries without Pi hardware."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from polstation.config import load_config
from polstation.health.recording_summary import (
    append_observation,
    rebuild_recording_summary,
)
from polstation.health.system_summary import system_summary


ROOT = Path(__file__).resolve().parents[1]


class OperationalSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.config = load_config(ROOT / "config/default.yaml")
        self.config["storage"]["data_root"] = str(root / "data")
        self.config["storage"]["state_root"] = str(root / "state")
        (root / "data").mkdir()
        (root / "state").mkdir()

    def manifest(self, observation_id="obs-1"):
        return {
            "complete": True,
            "observation_id": observation_id,
            "started_at_utc": "2026-11-12T12:00:00+00:00",
            "completed_at_utc": "2026-11-12T12:00:01+00:00",
            "capture": {"exposure_requested_us": 30000, "frames": [
                {"byte_count": 100}, {"byte_count": 100}, {"byte_count": 100}
            ]},
            "exposure_control": {
                "next_exposure_us": 30000,
                "brightest_percentile_dn": 2880,
                "settling": {"status": "converged", "converged": True,
                             "test_count": 2},
            },
            "sensor_snapshot": {"sensors": {}},
        }

    def test_rebuild_counts_only_valid_complete_manifests(self):
        first = Path(self.config["storage"]["data_root"]) / "valid"
        first.mkdir()
        (first / "manifest.json").write_text(json.dumps(self.manifest()))
        invalid = Path(self.config["storage"]["data_root"]) / "invalid"
        invalid.mkdir()
        (invalid / "manifest.json").write_text(json.dumps({"complete": False}))
        value = rebuild_recording_summary(
            self.config, now=datetime(2026, 11, 12, 13, tzinfo=timezone.utc)
        )
        self.assertEqual(value["totals"]["complete_observations"], 1)
        self.assertEqual(value["totals"]["raw_frames"], 3)
        self.assertEqual(value["totals"]["raw_bytes"], 300)

    def test_append_is_idempotent(self):
        rebuild_recording_summary(self.config)
        append_observation(self.config, self.manifest())
        value = append_observation(self.config, self.manifest())
        self.assertEqual(value["totals"]["complete_observations"], 1)

    def test_system_summary_tracks_boot_and_storage(self):
        now = datetime(2026, 11, 12, 13, tzinfo=timezone.utc)
        first = system_summary(
            self.config, now=now, uptime=120, boot_id="boot-a", previous={}
        )
        second = system_summary(
            self.config, now=now, uptime=130, boot_id="boot-a", previous=first
        )
        self.assertEqual(first["observed_boot_count"], 1)
        self.assertEqual(second["observed_boot_count"], 1)
        self.assertEqual(len(second["recent_boots"]), 1)
        self.assertGreater(second["storage"]["total_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
