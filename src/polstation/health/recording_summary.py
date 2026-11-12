"""Bounded operational index derived from immutable observation bundles."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from polstation.storage.manifests import write_json


RECENT_DAYS = 7
MAX_RECENT_EVENTS = 1200


def _observation_record(manifest):
    capture = manifest.get("capture", {})
    exposure = manifest.get("exposure_control", {})
    settling = exposure.get("settling") or {}
    frames = capture.get("frames", [])
    power = (
        manifest.get("sensor_snapshot", {})
        .get("sensors", {})
        .get("epever", {})
        .get("values", {})
    )
    return {
        "kind": "complete",
        "observation_id": manifest.get("observation_id"),
        "started_at_utc": manifest.get("started_at_utc"),
        "completed_at_utc": manifest.get("completed_at_utc"),
        "exposure_us": capture.get("exposure_requested_us"),
        "next_exposure_us": exposure.get("next_exposure_us"),
        "brightest_percentile_dn": exposure.get("brightest_percentile_dn"),
        "settling_status": settling.get("status"),
        "settling_converged": settling.get("converged"),
        "settling_test_count": settling.get("test_count"),
        "frame_count": len(frames),
        "raw_bytes": sum(frame.get("byte_count") or 0 for frame in frames),
        "battery_soc_percent": power.get("battery_soc_percent"),
        "battery_voltage_v": power.get("battery_voltage_v"),
        "battery_net_current_a": power.get("battery_net_current_a"),
        "pv_power_w": power.get("pv_power_w"),
        "load_power_w": power.get("load_power_w"),
    }


def _failure_record(failure):
    return {
        "kind": "failed",
        "observation_id": failure.get("observation_id"),
        "started_at_utc": failure.get("started_at_utc"),
        "failed_at_utc": failure.get("failed_at_utc"),
        "exposure_us": failure.get("exposure_requested_us"),
        "attempt_count": len(failure.get("attempts", [])),
    }


def _parse(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def rebuild_recording_summary(config, *, now=None):
    """Scan immutable completion markers once at recorder startup."""
    now = now or datetime.now(timezone.utc)
    root = Path(config["storage"]["data_root"])
    observations = []
    failures = []
    total_raw_frames = 0
    total_raw_bytes = 0
    complete_count = 0
    failed_count = 0
    first_observation_at = None
    last_observation_at = None

    if root.exists():
        for path in root.rglob("manifest.json"):
            try:
                manifest = json.loads(path.read_text())
                if not manifest.get("complete"):
                    continue
                record = _observation_record(manifest)
                observations.append(record)
                complete_count += 1
                total_raw_frames += record["frame_count"]
                total_raw_bytes += record["raw_bytes"]
                stamp = record["started_at_utc"]
                if stamp and (first_observation_at is None or stamp < first_observation_at):
                    first_observation_at = stamp
                if stamp and (last_observation_at is None or stamp > last_observation_at):
                    last_observation_at = stamp
            except (OSError, ValueError, TypeError):
                continue
        for path in root.rglob("failure.json"):
            try:
                failures.append(_failure_record(json.loads(path.read_text())))
                failed_count += 1
            except (OSError, ValueError, TypeError):
                continue

    cutoff = now - timedelta(days=RECENT_DAYS)
    observations = [
        item for item in observations
        if (_parse(item.get("started_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))
        >= cutoff
    ]
    failures = [
        item for item in failures
        if (_parse(item.get("started_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))
        >= cutoff
    ]
    observations.sort(key=lambda item: item.get("started_at_utc") or "")
    failures.sort(key=lambda item: item.get("started_at_utc") or "")
    value = {
        "schema_version": 1,
        "mode": "recording-summary",
        "updated_at_utc": now.isoformat(),
        "recent_days": RECENT_DAYS,
        "totals": {
            "complete_observations": complete_count,
            "failed_observations": failed_count,
            "raw_frames": total_raw_frames,
            "raw_bytes": total_raw_bytes,
            "first_observation_at_utc": first_observation_at,
            "last_observation_at_utc": last_observation_at,
        },
        "recent_observations": observations[-MAX_RECENT_EVENTS:],
        "recent_failures": failures[-MAX_RECENT_EVENTS:],
    }
    write_json(
        Path(config["storage"]["state_root"]) / "recording-summary.json",
        value,
        replace=True,
    )
    return value


def append_observation(config, manifest):
    """Update the bounded index after one immutable manifest is published."""
    path = Path(config["storage"]["state_root"]) / "recording-summary.json"
    try:
        value = json.loads(path.read_text())
        if value.get("mode") != "recording-summary":
            raise ValueError("invalid recording summary")
    except (OSError, ValueError, TypeError):
        return rebuild_recording_summary(config)
    record = _observation_record(manifest)
    totals = value["totals"]
    if not any(
        item.get("observation_id") == record["observation_id"]
        for item in value.get("recent_observations", [])
    ):
        totals["complete_observations"] += 1
        totals["raw_frames"] += record["frame_count"]
        totals["raw_bytes"] += record["raw_bytes"]
    totals["first_observation_at_utc"] = (
        totals.get("first_observation_at_utc") or record["started_at_utc"]
    )
    totals["last_observation_at_utc"] = record["started_at_utc"]
    recent = [
        item for item in value.get("recent_observations", [])
        if item.get("observation_id") != record["observation_id"]
    ]
    recent.append(record)
    value["recent_observations"] = recent[-MAX_RECENT_EVENTS:]
    value["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(path, value, replace=True)
    return value


def append_failure(config, failure):
    """Update the bounded index after one retained failure marker."""
    path = Path(config["storage"]["state_root"]) / "recording-summary.json"
    try:
        value = json.loads(path.read_text())
        if value.get("mode") != "recording-summary":
            raise ValueError("invalid recording summary")
    except (OSError, ValueError, TypeError):
        return rebuild_recording_summary(config)
    record = _failure_record(failure)
    if not any(
        item.get("observation_id") == record["observation_id"]
        for item in value.get("recent_failures", [])
    ):
        value["totals"]["failed_observations"] += 1
    recent = [
        item for item in value.get("recent_failures", [])
        if item.get("observation_id") != record["observation_id"]
    ]
    recent.append(record)
    value["recent_failures"] = recent[-MAX_RECENT_EVENTS:]
    value["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json(path, value, replace=True)
    return value
