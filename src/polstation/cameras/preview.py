"""Bounded, preview-only Vimba capture and file-backed dashboard snapshots."""

import argparse
import base64
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import signal
import threading
import time

from polstation.config import load_config
from polstation.logging.setup import configure
from polstation.polarization.preview import encode_png, legend_rgb, polarization_rgb, sample_mono8
from polstation.storage.layout import prepare_state
from polstation.storage.manifests import write_json

logger = logging.getLogger(__name__)


def mono8_preview_png(buffer, width, height, *, max_width=640, max_height=400):
    """Encode a bounded downsampled Mono8 frame as a browser-native PNG."""
    sampled_width, sampled_height, pixels = sample_mono8(
        buffer, width, height, max_width=max_width, max_height=max_height
    )
    return encode_png(pixels, sampled_width, sampled_height)


def _polarization_snapshot(config, sampled):
    configured = [camera for camera in config["cameras"] if camera["polarizer_angle_deg"] is not None]
    if not configured:
        return {"state": "unconfigured", "error": "Set local camera IDs and analyser angles 0, 45, and 90"}
    try:
        by_angle = {camera["polarizer_angle_deg"]: sampled[camera["id"]] for camera in configured}
        dimensions = {(item[0], item[1]) for item in by_angle.values()}
        if len(dimensions) != 1:
            raise ValueError("camera preview dimensions differ")
        width, height = dimensions.pop()
        dolp, aop = polarization_rgb(by_angle[0][2], by_angle[45][2], by_angle[90][2])
        def encode(value):
            return base64.b64encode(value).decode("ascii")

        return {
            "state": "live",
            "registered": False,
            "synchronized": False,
            "calibrated": False,
            "aop_reference": "sensor-relative",
            "width": width,
            "height": height,
            "dolp_preview_png": encode(encode_png(dolp, width, height, channels=3)),
            "aop_preview_png": encode(encode_png(aop, width, height, channels=3)),
            "dolp_legend_png": encode(encode_png(legend_rgb("dolp"), 256, 12, channels=3)),
            "aop_legend_png": encode(encode_png(legend_rgb("aop"), 256, 12, channels=3)),
        }
    except (KeyError, ValueError) as error:
        return {
            "state": "unavailable",
            "error": str(error),
            "registered": False,
            "synchronized": False,
            "calibrated": False,
        }


def _read_feature(camera, *names):
    for name in names:
        try:
            return camera.get_feature_by_name(name).get()
        except Exception:
            pass
    return None


def _feature(camera, *names):
    for name in names:
        try:
            return camera.get_feature_by_name(name)
        except Exception:
            pass
    raise RuntimeError(f"camera {camera.get_id()} has none of features: {', '.join(names)}")


def _percentile_dn(pixels, percentile):
    """Return a nearest-rank percentile from bounded 8-bit preview pixels."""
    if not pixels:
        raise ValueError("cannot measure brightness from an empty preview")
    histogram = [0] * 256
    for value in pixels:
        histogram[value] += 1
    rank = max(1, int((percentile / 100) * len(pixels) + 0.999999999))
    cumulative = 0
    for value, count in enumerate(histogram):
        cumulative += count
        if cumulative >= rank:
            return value
    return 255


def _next_shared_exposure(current_us, brightest_dn, settings):
    """Choose one bounded next exposure for all cameras from the brightest preview."""
    minimum = settings["minimum_exposure_us"]
    maximum = settings["maximum_exposure_us"]
    target = settings["target_brightness_dn"]
    tolerance = settings["brightness_tolerance_dn"]
    maximum_step = settings["maximum_step_factor"]
    if abs(brightest_dn - target) <= tolerance:
        return current_us
    if brightest_dn <= 0:
        factor = maximum_step
    elif brightest_dn >= 255:
        # A clipped percentile contains no information about how far over-range
        # the scene is, so make one conservative bounded downward step.
        factor = 1 / maximum_step
    else:
        factor = target / brightest_dn
        factor = min(maximum_step, max(1 / maximum_step, factor))
    return max(minimum, min(maximum, round(current_us * factor)))


class FilePreviewSource:
    """Read the atomic latest-preview file without importing or opening Vimba."""

    mode = "hardware-preview"

    def __init__(self, config):
        self.path = Path(config["storage"]["state_root"]) / "camera-previews.json"
        self.sensor_path = Path(config["storage"]["state_root"]) / "sensor-preview.json"
        self.stale_after_seconds = config["dashboard"]["stale_after_seconds"]

    def _sensor_snapshot(self, now):
        try:
            value = json.loads(self.sensor_path.read_text())
            if value.get("mode") != "hardware-sensors" or not isinstance(value.get("sensors"), dict):
                raise ValueError("invalid sensor snapshot")
            for sensor in value["sensors"].values():
                sampled = sensor.get("sampled_at_utc")
                sensor["age_seconds"] = max(
                    0.0, (now - datetime.fromisoformat(sampled)).total_seconds()
                ) if sampled else None
                if sensor.get("state") == "live" and sensor["age_seconds"] > self.stale_after_seconds:
                    sensor["state"] = "stale"
            return value["sensors"]
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            return {
                name: {"state": "unavailable", "sampled_at_utc": None,
                       "age_seconds": None, "values": {}, "error": str(error)}
                for name in ("bme280", "epever")
            }

    def snapshot(self, scenario="live"):
        if scenario != "live":
            raise ValueError("hardware preview has no simulated fault scenarios")
        try:
            value = json.loads(self.path.read_text())
            if value.get("mode") != self.mode or not isinstance(value.get("cameras"), list):
                raise ValueError("invalid preview snapshot")
            now = datetime.now(timezone.utc)
            for camera in value["cameras"]:
                captured = camera.get("captured_at_utc")
                camera["age_seconds"] = max(0.0, (now - datetime.fromisoformat(captured)).total_seconds()) if captured else None
                if camera["state"] == "live" and camera["age_seconds"] > self.stale_after_seconds:
                    camera["state"] = "stale"
            value["hardware_ready"] = bool(value["cameras"]) and all(
                camera["state"] == "live" for camera in value["cameras"]
            )
            if not value["hardware_ready"] and value.get("polarization", {}).get("state") == "live":
                value["polarization"]["state"] = "stale"
            value["sensors"] = self._sensor_snapshot(now)
            return value
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            return {"schema_version": 1, "mode": self.mode, "hardware_ready": False,
                    "recording": False, "synchronization": "unverified",
                    "error": str(error), "cameras": [],
                    "sensors": self._sensor_snapshot(datetime.now(timezone.utc))}


def run_hardware_preview(config, stop, *, interval=1.0, timeout_ms=5000):
    """Publish sequential real-camera previews; never write observations."""
    try:
        from vmbpy import FrameStatus, PixelFormat, VmbSystem
    except ImportError as error:
        raise RuntimeError("VmbPy is required for hardware preview mode") from error

    prepare_state(config)
    output = Path(config["storage"]["state_root"]) / "camera-previews.json"
    exposure_settings = config["camera_preview"]
    exposure_mode = exposure_settings["exposure_mode"]
    shared_exposure_us = exposure_settings["initial_exposure_us"]
    counters = {}
    with VmbSystem.get_instance() as vmb:
        cameras = sorted(vmb.get_all_cameras(), key=lambda camera: camera.get_id())
        if len(cameras) != 3:
            raise RuntimeError(f"expected three cameras, found {len(cameras)}")
        with ExitStack() as stack:
            opened = [stack.enter_context(camera) for camera in cameras]
            originals = []
            try:
                for camera in opened:
                    packet = camera.get_feature_by_name("GevSCPSPacketSize")
                    trigger = camera.get_feature_by_name("TriggerMode")
                    exposure = _feature(camera, "ExposureTimeAbs", "ExposureTime")
                    exposure_auto = _feature(camera, "ExposureAuto")
                    original = {
                        "camera": camera,
                        "packet": packet,
                        "packet_value": packet.get(),
                        "pixel_format": camera.get_pixel_format(),
                        "trigger": trigger,
                        "trigger_value": trigger.get(),
                        "exposure": exposure,
                        "exposure_value": exposure.get(),
                        "exposure_auto": exposure_auto,
                        "exposure_auto_value": exposure_auto.get(),
                    }
                    originals.append(original)
                    packet.set(1500)
                    camera.set_pixel_format(PixelFormat.Mono8)
                    trigger.set("Off")
                    exposure_auto.set("Off")
                    exposure.set(shared_exposure_us)

                while not stop.is_set():
                    cycle_started = time.monotonic()
                    snapshots = []
                    sampled = {}
                    for camera in opened:
                        camera_id = camera.get_id()
                        try:
                            frame = camera.get_frame(timeout_ms=timeout_ms)
                            if frame.get_status() != FrameStatus.Complete:
                                raise RuntimeError(f"incomplete frame: {frame.get_status()}")
                            width, height = frame.get_width(), frame.get_height()
                            preview_width, preview_height, preview_pixels = sample_mono8(bytes(frame.get_buffer()), width, height)
                            sampled[camera_id] = (preview_width, preview_height, preview_pixels)
                            encoded = base64.b64encode(encode_png(preview_pixels, preview_width, preview_height)).decode("ascii")
                            counters[camera_id] = counters.get(camera_id, 0) + 1
                            snapshots.append({
                                "id": camera_id, "model": camera.get_model(), "state": "live",
                                "simulated": False, "frame_number": counters[camera_id],
                                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                                "age_seconds": 0.0, "exposure_us": _read_feature(camera, "ExposureTimeAbs", "ExposureTime"),
                                "gain_db": _read_feature(camera, "Gain", "GainRaw"),
                                "pixel_format": str(frame.get_pixel_format()).rsplit(".", 1)[-1],
                                "device_timestamp": frame.get_timestamp(), "preview_png": encoded,
                            })
                        except Exception as error:
                            logger.exception("Preview capture failed for %s", camera_id)
                            snapshots.append({"id": camera_id, "model": camera.get_model(), "state": "disconnected",
                                              "simulated": False, "frame_number": counters.get(camera_id),
                                              "captured_at_utc": None, "age_seconds": None, "exposure_us": None,
                                              "gain_db": None, "pixel_format": None, "device_timestamp": None,
                                              "preview_png": None, "error": str(error)})
                    brightest_dn = None
                    next_exposure_us = shared_exposure_us
                    if len(sampled) == len(opened):
                        brightest_dn = max(
                            _percentile_dn(item[2], exposure_settings["brightness_percentile"])
                            for item in sampled.values()
                        )
                        if exposure_mode == "shared_auto":
                            next_exposure_us = _next_shared_exposure(
                                shared_exposure_us, brightest_dn, exposure_settings
                            )
                    write_json(output, {"schema_version": 1, "mode": "hardware-preview",
                                       "hardware_ready": all(item["state"] == "live" for item in snapshots),
                                       "recording": False, "synchronization": "unverified",
                                       "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                                       "exposure_control": {
                                           "mode": exposure_mode,
                                           "shared": True,
                                           "applied_exposure_us": shared_exposure_us,
                                           "next_exposure_us": next_exposure_us,
                                           "brightness_percentile": exposure_settings["brightness_percentile"],
                                           "brightest_percentile_dn": brightest_dn,
                                           "target_brightness_dn": exposure_settings["target_brightness_dn"],
                                           "minimum_exposure_us": exposure_settings["minimum_exposure_us"],
                                           "maximum_exposure_us": exposure_settings["maximum_exposure_us"],
                                       },
                                       "polarization": _polarization_snapshot(config, sampled),
                                       "cameras": snapshots}, replace=True)
                    if next_exposure_us != shared_exposure_us:
                        for original in originals:
                            original["exposure"].set(next_exposure_us)
                        shared_exposure_us = next_exposure_us
                    stop.wait(max(0.0, interval - (time.monotonic() - cycle_started)))
            finally:
                for original in reversed(originals):
                    try:
                        original["exposure"].set(original["exposure_value"])
                        original["exposure_auto"].set(original["exposure_auto_value"])
                        original["trigger"].set(original["trigger_value"])
                        original["camera"].set_pixel_format(original["pixel_format"])
                        original["packet"].set(original["packet_value"])
                    except Exception:
                        logger.exception(
                            "Could not restore preview settings for %s",
                            original["camera"].get_id(),
                        )


def main():
    parser = argparse.ArgumentParser(description="Publish bounded real-camera previews; never record observations")
    parser.add_argument("--config", required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    configure()
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    run_hardware_preview(load_config(args.config), stop, interval=args.interval)


if __name__ == "__main__":
    main()
