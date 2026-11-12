"""Timed, immutable three-camera Mono12 observation recording."""
import argparse
from array import array
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import logging
import math
import os
from pathlib import Path
import signal
import sys
import threading
import time
import uuid

from polstation.cameras.preview import (
    _feature,
    _focus_metric,
    _parallel_camera_calls,
    _polarization_snapshot,
    _read_feature,
)
from polstation.config import load_config
from polstation.health.recording_summary import (
    append_failure,
    append_observation,
    rebuild_recording_summary,
)
from polstation.logging.setup import configure
from polstation.polarization.preview import (
    central_circular_roi,
    encode_png,
    sample_mono12,
)
from polstation.storage.layout import free_bytes, prepare
from polstation.storage.manifests import config_digest, write_json

logger = logging.getLogger(__name__)


class ObservationCaptureError(RuntimeError):
    """A bounded observation attempt failed; its partial bundle is preserved."""

    def __init__(self, message, path):
        super().__init__(message)
        self.path = Path(path)


def exposure_timeout_ms(exposure_us, margin_seconds):
    """Return a timeout that covers the requested exposure plus fixed transport margin."""
    return max(1, math.ceil(exposure_us / 1000 + margin_seconds * 1000))


def next_utc_slot(now, interval_seconds):
    """Return the next wall-clock-aligned UTC slot, never the current/past slot."""
    timestamp = now.timestamp()
    next_timestamp = (math.floor(timestamp / interval_seconds) + 1) * interval_seconds
    return datetime.fromtimestamp(next_timestamp, timezone.utc)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_raw(path, payload):
    path = Path(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return hashlib.sha256(payload).hexdigest()


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _observation_id(started_at):
    stamp = started_at.strftime("%Y%m%dT%H%M%S.%fZ")
    return f"obs-{stamp}-{uuid.uuid4().hex[:8]}"


def _sensor_snapshot(config, read_at):
    path = Path(config["storage"]["state_root"]) / "sensor-preview.json"
    try:
        value = json.loads(path.read_text())
        if value.get("mode") != "hardware-sensors" or not isinstance(value.get("sensors"), dict):
            raise ValueError("invalid sensor preview snapshot")
        return {
            "state": "available",
            "association": "latest diagnostic sample at observation start; timing unvalidated",
            "read_at_utc": read_at.isoformat(),
            "source_path": str(path),
            "source_updated_at_utc": value.get("updated_at_utc"),
            "sensors": value["sensors"],
        }
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {
            "state": "unavailable",
            "association": "no validated sensor sample associated",
            "read_at_utc": read_at.isoformat(),
            "sensors": {},
            "error": str(error),
        }


def _mono12_roi_percentile(payload, width, height, percentile):
    expected_bytes = width * height * 2
    if len(payload) != expected_bytes:
        raise ValueError(
            f"Mono12 buffer length {len(payload)} does not match {width}x{height}"
        )
    pixels = array("H")
    pixels.frombytes(payload)
    if sys.byteorder != "little":
        pixels.byteswap()
    center_x = width / 2
    center_y = height / 2
    radius = 0.30 * min(width, height)
    radius_squared = radius * radius
    x_start = max(0, math.floor(center_x - radius))
    x_stop = min(width, math.ceil(center_x + radius))
    y_start = max(0, math.floor(center_y - radius))
    y_stop = min(height, math.ceil(center_y + radius))
    histogram = [0] * 4096
    count = 0
    for y in range(y_start, y_stop):
        dy_squared = (y + 0.5 - center_y) ** 2
        row = y * width
        for x in range(x_start, x_stop):
            if (x + 0.5 - center_x) ** 2 + dy_squared <= radius_squared:
                histogram[pixels[row + x] & 0x0FFF] += 1
                count += 1
    if count == 0:
        raise ValueError("central circular ROI contains no pixels")
    rank = max(1, math.ceil(percentile / 100 * count))
    cumulative = 0
    for value, frequency in enumerate(histogram):
        cumulative += frequency
        if cumulative >= rank:
            return value
    return 4095


def _next_exposure(current_us, brightness_dn, settings):
    if settings["exposure_mode"] == "fixed":
        return current_us
    target = settings["target_brightness_dn"]
    tolerance = settings["brightness_tolerance_dn"]
    maximum_step = settings["maximum_step_factor"]
    if target - tolerance <= brightness_dn <= target + tolerance:
        candidate = current_us
    elif brightness_dn >= 4095:
        # A clipped percentile is only a lower bound on scene brightness. Take
        # the largest permitted downward step so settling escapes saturation
        # promptly rather than treating 4095 as a precise measurement.
        candidate = current_us / maximum_step
    elif brightness_dn <= 0:
        candidate = current_us * maximum_step
    else:
        factor = min(maximum_step, max(1 / maximum_step, target / brightness_dn))
        candidate = current_us * factor
    return min(
        settings["maximum_exposure_us"],
        max(settings["minimum_exposure_us"], round(candidate)),
    )


def _capture_frames_by_id(captured, expected_ids):
    frames = captured.get("frames", [])
    by_id = {frame.get("camera_id"): frame for frame in frames}
    if len(by_id) != len(frames) or set(by_id) != set(expected_ids):
        raise ValueError("capture result must contain each configured camera exactly once")
    return frames


def _complete_mono12_frames(frames):
    return all(
        frame.get("status") == "complete"
        and frame.get("raw") is not None
        and frame.get("pixel_format") == "Mono12"
        for frame in frames
    )


def settle_exposure(config, capture_attempt, initial_exposure_us, *, monotonic=None):
    """Bound shared exposure with diagnostic probes before a saved observation.

    Probe pixels are deliberately not persisted. Bounded probe metadata and ROI
    percentiles are returned for the immutable observation manifest. The final
    scientific capture is always a fresh three-camera acquisition performed by
    ``record_observation`` after this function returns.
    """
    settings = config["observation_capture"]
    exposure_us = initial_exposure_us
    if settings["exposure_mode"] == "fixed":
        return {
            "mode": "fixed",
            "status": "not-required",
            "converged": True,
            "initial_exposure_us": initial_exposure_us,
            "selected_exposure_us": initial_exposure_us,
            "test_count": 0,
            "elapsed_seconds": 0.0,
            "tests": [],
        }

    monotonic = monotonic or time.monotonic
    started = monotonic()
    expected_ids = [camera["id"] for camera in config["cameras"]]
    tests = []
    selected_exposure_us = exposure_us
    status = "attempt-limit"
    converged = False

    for test_number in range(1, settings["maximum_exposure_settling_attempts"] + 1):
        if tests and monotonic() - started >= settings["maximum_exposure_settling_seconds"]:
            status = "time-limit"
            break
        timeout_ms = exposure_timeout_ms(
            exposure_us, settings["timeout_margin_seconds"]
        )
        captured = capture_attempt(exposure_us, timeout_ms, test_number)
        frames = _capture_frames_by_id(captured, expected_ids)
        public_frames = [
            {key: value for key, value in frame.items() if key != "raw"}
            for frame in frames
        ]
        test = {
            "test": test_number,
            "exposure_requested_us": exposure_us,
            "timeout_ms": timeout_ms,
            "request_span_ms": captured.get("request_span_ms"),
            "frames": public_frames,
            "complete": _complete_mono12_frames(frames),
        }
        tests.append(test)
        if not test["complete"]:
            test["result"] = "incomplete"
            continue

        percentiles = {
            frame["camera_id"]: _mono12_roi_percentile(
                frame["raw"], frame["width"], frame["height"],
                settings["brightness_percentile"],
            )
            for frame in frames
        }
        brightest_dn = max(percentiles.values())
        candidate = _next_exposure(exposure_us, brightest_dn, settings)
        within_tolerance = (
            settings["target_brightness_dn"] - settings["brightness_tolerance_dn"]
            <= brightest_dn
            <= settings["target_brightness_dn"] + settings["brightness_tolerance_dn"]
        )
        test.update({
            "percentile_dn_by_camera": percentiles,
            "brightest_percentile_dn": brightest_dn,
            "next_exposure_us": candidate,
            "within_tolerance": within_tolerance,
            "result": "converged" if within_tolerance else "adjust",
        })
        selected_exposure_us = exposure_us
        if within_tolerance:
            status = "converged"
            converged = True
            break
        if candidate == exposure_us:
            status = "exposure-limit"
            break
        exposure_us = candidate
        selected_exposure_us = candidate

    return {
        "mode": "shared_auto",
        "status": status,
        "converged": converged,
        "initial_exposure_us": initial_exposure_us,
        "selected_exposure_us": selected_exposure_us,
        "test_count": len(tests),
        "elapsed_seconds": round(monotonic() - started, 6),
        "maximum_attempts": settings["maximum_exposure_settling_attempts"],
        "maximum_seconds": settings["maximum_exposure_settling_seconds"],
        "tests": tests,
    }


def _attempt_public_record(attempt):
    return {
        "attempt": attempt["attempt"],
        "request_span_ms": attempt.get("request_span_ms"),
        "frames": [
            {key: value for key, value in frame.items() if key != "raw"}
            for frame in attempt["frames"]
        ],
    }


def record_observation(config, capture_attempt, exposure_us, *,
                       scheduled_for_utc=None, observation_id=None, now=None,
                       exposure_settling=None):
    """Record one immutable observation using a hardware or test capture callback."""
    now = now or (lambda: datetime.now(timezone.utc))
    started_at = now()
    if started_at.tzinfo is None:
        raise ValueError("observation timestamps must be timezone-aware")
    scheduled_for_utc = scheduled_for_utc or started_at
    observation_id = observation_id or _observation_id(started_at)
    root = Path(config["storage"]["data_root"])
    observation = root / started_at.strftime("%Y/%m/%d") / observation_id
    raw_directory = observation / "raw"
    raw_directory.mkdir(parents=True, exist_ok=False)
    write_json(observation / "config.json", config)
    sensor_snapshot = _sensor_snapshot(config, started_at)
    expected_ids = [camera["id"] for camera in config["cameras"]]
    timeout_ms = exposure_timeout_ms(
        exposure_us, config["observation_capture"]["timeout_margin_seconds"]
    )
    attempts = []
    selected_attempt = None

    for attempt_number in range(1, config["observation_capture"]["maximum_capture_attempts"] + 1):
        captured = capture_attempt(exposure_us, timeout_ms, attempt_number)
        frames = _capture_frames_by_id(captured, expected_ids)
        by_id = {frame["camera_id"]: frame for frame in frames}
        attempt = {
            "attempt": attempt_number,
            "request_span_ms": captured.get("request_span_ms"),
            "frames": [],
        }
        for index, camera_id in enumerate(expected_ids, start=1):
            frame = dict(by_id[camera_id])
            payload = frame.pop("raw", None)
            if payload is not None:
                filename = f"camera-{index:02d}.attempt-{attempt_number:03d}.mono12.raw"
                relative = Path("raw") / filename
                frame["relative_path"] = str(relative)
                frame["byte_count"] = len(payload)
                frame["sha256"] = _write_raw(observation / relative, payload)
                frame["raw"] = payload
            else:
                frame["relative_path"] = None
                frame["byte_count"] = None
                frame["sha256"] = None
                frame["raw"] = None
            attempt["frames"].append(frame)
        attempts.append(attempt)
        complete = _complete_mono12_frames(attempt["frames"])
        if complete:
            selected_attempt = attempt
            break

    _fsync_directory(raw_directory)
    public_attempts = [_attempt_public_record(attempt) for attempt in attempts]
    if selected_attempt is None:
        failure = {
            "schema_version": 1,
            "kind": "timed-observation-failure",
            "complete": False,
            "observation_id": observation_id,
            "scheduled_for_utc": scheduled_for_utc.isoformat(),
            "started_at_utc": started_at.isoformat(),
            "failed_at_utc": now().isoformat(),
            "config_sha256": config_digest(config),
            "provenance": config["provenance"],
            "exposure_requested_us": exposure_us,
            "timeout_ms": timeout_ms,
            "attempts": public_attempts,
        }
        write_json(observation / "failure.json", failure)
        raise ObservationCaptureError(
            f"no complete three-camera attempt after {len(attempts)} attempts",
            observation,
        )

    selected_frames = selected_attempt["frames"]
    percentiles = {
        frame["camera_id"]: _mono12_roi_percentile(
            frame["raw"], frame["width"], frame["height"],
            config["observation_capture"]["brightness_percentile"],
        )
        for frame in selected_frames
    }
    brightest_dn = max(percentiles.values())
    next_exposure_us = _next_exposure(
        exposure_us, brightest_dn, config["observation_capture"]
    )
    completed_at = now()
    manifest = {
        "schema_version": 1,
        "kind": "timed-sky-observation",
        "complete": True,
        "observation_id": observation_id,
        "scheduled_for_utc": scheduled_for_utc.isoformat(),
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "software": {"package": "polstation", "version": version("polstation")},
        "provenance": config["provenance"],
        "config_sha256": config_digest(config),
        "config_snapshot": {
            "relative_path": "config.json",
            "sha256": _sha256(observation / "config.json"),
        },
        "synchronization": "software-parallel-unverified",
        "raw_format": {
            "pixel_format": "Mono12",
            "byte_order": "little-endian",
            "packing": "12-bit values in 16-bit words",
            "processing": "none; original returned frame buffers",
        },
        "capture": {
            "selected_attempt": selected_attempt["attempt"],
            "exposure_requested_us": exposure_us,
            "timeout_ms": timeout_ms,
            "request_span_ms": selected_attempt.get("request_span_ms"),
            "frames": [
                {key: value for key, value in frame.items() if key != "raw"}
                for frame in selected_frames
            ],
            "attempts": public_attempts,
        },
        "exposure_control": {
            "mode": config["observation_capture"]["exposure_mode"],
            "brightness_percentile": config["observation_capture"]["brightness_percentile"],
            "roi": "central circular ROI; radius 30% of smaller image dimension",
            "percentile_dn_by_camera": percentiles,
            "brightest_percentile_dn": brightest_dn,
            "next_exposure_us": next_exposure_us,
            "settling": exposure_settling or {
                "mode": config["observation_capture"]["exposure_mode"],
                "status": "not-performed",
                "converged": None,
                "initial_exposure_us": exposure_us,
                "selected_exposure_us": exposure_us,
                "test_count": 0,
                "tests": [],
            },
            "validated_for_scientific_use": False,
        },
        "sensor_snapshot": sensor_snapshot,
        "derived_products": [],
    }
    write_json(observation / "manifest.json", manifest)
    return {
        "path": observation,
        "manifest": manifest,
        "next_exposure_us": next_exposure_us,
    }


def _publish_recorded_preview(config, result):
    """Publish bounded diagnostic images derived from one completed raw bundle."""
    observation = result["path"]
    manifest = result["manifest"]
    frames = manifest["capture"]["frames"]
    frames_by_id = {frame["camera_id"]: frame for frame in frames}
    sampled = {}
    cameras = []
    relative_observation = str(observation.relative_to(config["storage"]["data_root"]))

    for camera_config in config["cameras"]:
        camera_id = camera_config["id"]
        frame = frames_by_id[camera_id]
        payload = (observation / frame["relative_path"]).read_bytes()
        width, height, pixels = sample_mono12(
            payload, frame["width"], frame["height"]
        )
        sampled[camera_id] = (width, height, pixels)
        roi_mask, roi = central_circular_roi(width, height)
        try:
            focus_metric = _focus_metric(pixels, width, height, roi_mask)
        except ValueError:
            focus_metric = None
        cameras.append({
            "id": camera_id,
            "model": frame.get("model") or camera_config["model"],
            "state": "recorded",
            "simulated": False,
            "frame_number": frame.get("frame_id"),
            "captured_at_utc": frame.get("capture_completed_at_utc"),
            "capture_request_at_utc": frame.get("capture_request_at_utc"),
            "capture_completed_at_utc": frame.get("capture_completed_at_utc"),
            "age_seconds": 0.0,
            "exposure_us": frame.get("exposure_readback_us"),
            "gain_db": frame.get("gain_db"),
            "focus_metric": focus_metric,
            "focus_metric_method": (
                "central-ROI variance of 4-neighbour Laplacian on diagnostic "
                "Mono12-to-Mono8 rendering (DN^2)"
            ),
            "focus_roi": roi,
            "pixel_format": "Mono12 (diagnostic 8-bit rendering)",
            "device_timestamp": frame.get("device_timestamp"),
            "preview_png": base64.b64encode(
                encode_png(pixels, width, height)
            ).decode("ascii"),
            "source_observation_id": manifest["observation_id"],
            "source_observation_relative_path": relative_observation,
            "source_raw_relative_path": frame["relative_path"],
            "source_raw_sha256": frame["sha256"],
        })

    polarization = _polarization_snapshot(
        config,
        sampled,
        manifest["capture"]["exposure_requested_us"],
    )
    if polarization.get("state") == "live":
        polarization["state"] = "recorded"
    polarization.update({
        "source_observation_id": manifest["observation_id"],
        "source_observation_relative_path": relative_observation,
        "diagnostic_only": True,
    })
    output = Path(config["storage"]["state_root"]) / "observation-preview.json"
    write_json(output, {
        "schema_version": 1,
        "mode": "recorded-observation-preview",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "observation_id": manifest["observation_id"],
        "observation_relative_path": relative_observation,
        "observation_completed_at_utc": manifest["completed_at_utc"],
        "config_sha256": manifest["config_sha256"],
        "provenance": manifest["provenance"],
        "diagnostic_only": True,
        "raw_files_unchanged": True,
        "cameras": cameras,
        "polarization": polarization,
    }, replace=True)


class VmbMono12Recorder:
    """Own and configure the three Vimba cameras for timed raw capture."""

    def __init__(self, config):
        self.config = config
        self.stack = ExitStack()
        self.opened = []
        self.originals = []
        self.executor = None
        self.FrameStatus = None

    def __enter__(self):
        try:
            from vmbpy import FrameStatus, PixelFormat, VmbSystem
        except ImportError as error:
            raise RuntimeError("VmbPy is required for observation recording") from error
        settings = self.config["observation_capture"]
        if settings["stream_bytes_per_second"] is None:
            raise RuntimeError(
                "observation_capture.stream_bytes_per_second must be commissioned "
                "before parallel hardware recording"
            )
        self.FrameStatus = FrameStatus
        vmb = self.stack.enter_context(VmbSystem.get_instance())
        discovered = {camera.get_id(): camera for camera in vmb.get_all_cameras()}
        configured_ids = [camera["id"] for camera in self.config["cameras"]]
        missing = sorted(set(configured_ids) - set(discovered))
        if missing:
            raise RuntimeError(f"configured cameras not discovered: {', '.join(missing)}")
        if len(discovered) != 3:
            raise RuntimeError(f"expected exactly three cameras, found {len(discovered)}")
        self.opened = [
            self.stack.enter_context(discovered[camera_id])
            for camera_id in configured_ids
        ]
        try:
            for camera in self.opened:
                packet = camera.get_feature_by_name("GevSCPSPacketSize")
                stream = camera.get_feature_by_name("StreamBytesPerSecond")
                trigger = camera.get_feature_by_name("TriggerMode")
                exposure = _feature(camera, "ExposureTimeAbs", "ExposureTime")
                exposure_auto = _feature(camera, "ExposureAuto")
                gain_auto = _feature(camera, "GainAuto")
                gain = _feature(camera, "Gain", "GainRaw")
                gamma = _feature(camera, "Gamma")
                original = {
                    "camera": camera,
                    "pixel_format": camera.get_pixel_format(),
                    "packet": (packet, packet.get()),
                    "stream": (stream, stream.get()),
                    "trigger": (trigger, trigger.get()),
                    "exposure": (exposure, exposure.get()),
                    "exposure_auto": (exposure_auto, exposure_auto.get()),
                    "gain_auto": (gain_auto, gain_auto.get()),
                    "gain": (gain, gain.get()),
                    "gamma": (gamma, gamma.get()),
                }
                self.originals.append(original)
                packet.set(1500)
                stream.set(settings["stream_bytes_per_second"])
                camera.set_pixel_format(PixelFormat.Mono12)
                trigger.set("Off")
                exposure_auto.set("Off")
                gain_auto.set("Off")
                gain.set(0.0)
                gamma.set(1.0)
            self.executor = ThreadPoolExecutor(
                max_workers=3, thread_name_prefix="observation-camera"
            )
            return self
        except Exception:
            self.__exit__(*sys.exc_info())
            raise

    def capture_attempt(self, exposure_us, timeout_ms, attempt_number):
        for original in self.originals:
            original["exposure"][0].set(exposure_us)
        outcomes = _parallel_camera_calls(
            self.opened,
            lambda camera: camera.get_frame(timeout_ms=timeout_ms),
            executor=self.executor,
        )
        request_span_ms = 1000 * (
            max(item["requested_monotonic"] for item in outcomes)
            - min(item["requested_monotonic"] for item in outcomes)
        )
        frames = []
        for outcome in outcomes:
            camera = outcome["camera"]
            record = {
                "camera_id": camera.get_id(),
                "model": camera.get_model(),
                "serial": camera.get_serial(),
                "capture_attempt": attempt_number,
                "capture_request_at_utc": outcome["requested_at_utc"],
                "capture_completed_at_utc": outcome["completed_at_utc"],
                "timestamp_source": "Pi UTC receipt time; exposure timing unverified",
                "exposure_readback_us": _read_feature(camera, "ExposureTimeAbs", "ExposureTime"),
                "gain_db": _read_feature(camera, "Gain", "GainRaw"),
                "gamma": _read_feature(camera, "Gamma"),
                "black_level": _read_feature(camera, "BlackLevel"),
                "device_temperature_c": _read_feature(camera, "DeviceTemperature"),
                "packet_size": _read_feature(camera, "GevSCPSPacketSize"),
                "stream_bytes_per_second": _read_feature(camera, "StreamBytesPerSecond"),
                "error": repr(outcome["error"]) if outcome["error"] is not None else None,
                "raw": None,
            }
            if outcome["error"] is None:
                frame = outcome["value"]
                status = frame.get_status()
                record.update({
                    "status": "complete" if status == self.FrameStatus.Complete else str(status),
                    "width": frame.get_width(),
                    "height": frame.get_height(),
                    "pixel_format": str(frame.get_pixel_format()).rsplit(".", 1)[-1],
                    "device_timestamp": frame.get_timestamp(),
                    "frame_id": frame.get_id(),
                    "raw": bytes(frame.get_buffer()),
                })
            else:
                record.update({
                    "status": "error", "width": None, "height": None,
                    "pixel_format": None, "device_timestamp": None, "frame_id": None,
                })
            frames.append(record)
        return {"request_span_ms": request_span_ms, "frames": frames}

    def __exit__(self, exc_type, exc_value, traceback):
        if self.executor is not None:
            self.executor.shutdown(wait=True, cancel_futures=True)
            self.executor = None
        for original in reversed(self.originals):
            try:
                for name in (
                    "gamma", "gain", "gain_auto", "exposure_auto", "exposure",
                    "trigger", "stream", "packet",
                ):
                    feature, value = original[name]
                    feature.set(value)
                original["camera"].set_pixel_format(original["pixel_format"])
            except Exception:
                logger.exception(
                    "Could not restore recording settings for %s",
                    original["camera"].get_id(),
                )
        self.originals.clear()
        self.stack.close()


def _read_recorder_state(path):
    try:
        value = json.loads(Path(path).read_text())
        return value if value.get("mode") == "observation-recorder" else {}
    except (OSError, ValueError, TypeError):
        return {}


def _publish_state(path, config, state, **values):
    write_json(path, {
        "schema_version": 1,
        "mode": "observation-recorder",
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "interval_seconds": config["observation_capture"]["interval_seconds"],
        "config_sha256": config_digest(config),
        "provenance": config["provenance"],
        **values,
    }, replace=True)


def run(config, stop, *, once=False, recorder_factory=VmbMono12Recorder):
    prepare(config)
    rebuild_recording_summary(config)
    state_path = Path(config["storage"]["state_root"]) / "observation-recorder.json"
    previous = _read_recorder_state(state_path)
    settings = config["observation_capture"]
    exposure_us = settings["initial_exposure_us"]
    if (
        previous.get("config_sha256") == config_digest(config)
        and isinstance(previous.get("next_exposure_us"), (int, float))
        and settings["minimum_exposure_us"]
        <= previous["next_exposure_us"]
        <= settings["maximum_exposure_us"]
    ):
        exposure_us = previous["next_exposure_us"]
    retained = {
        "last_acquisition_at_utc": previous.get("last_acquisition_at_utc"),
        "last_observation_id": previous.get("last_observation_id"),
        "last_observation_relative_path": previous.get("last_observation_relative_path"),
        "last_attempt_state": previous.get("last_attempt_state"),
        "last_error": previous.get("last_error"),
        "failed_observation_relative_path": previous.get(
            "failed_observation_relative_path"
        ),
    }
    with recorder_factory(config) as recorder:
        while not stop.is_set():
            if once:
                scheduled = datetime.now(timezone.utc)
            else:
                scheduled = next_utc_slot(
                    datetime.now(timezone.utc), settings["interval_seconds"]
                )
                while not stop.is_set():
                    remaining = (scheduled - datetime.now(timezone.utc)).total_seconds()
                    if remaining <= 0:
                        break
                    _publish_state(
                        state_path, config, "waiting",
                        next_acquisition_at_utc=scheduled.isoformat(),
                        applied_exposure_us=exposure_us,
                        next_exposure_us=exposure_us,
                        **retained,
                    )
                    stop.wait(min(remaining, config["acquisition"]["heartbeat_seconds"]))
                if stop.is_set():
                    break
            if free_bytes(config) < config["storage"]["minimum_free_bytes"]:
                logger.error("Low disk space; observation skipped and existing data retained")
                retained.update({
                    "last_attempt_state": "skipped-low-disk",
                    "last_error": "minimum free-space threshold reached; capture skipped",
                })
                _publish_state(
                    state_path, config, "low_disk",
                    next_acquisition_at_utc=None,
                    applied_exposure_us=exposure_us,
                    next_exposure_us=exposure_us,
                    **retained,
                )
            else:
                _publish_state(
                    state_path, config, "capturing",
                    next_acquisition_at_utc=None,
                    applied_exposure_us=exposure_us,
                    next_exposure_us=exposure_us,
                    **retained,
                )
                try:
                    _publish_state(
                        state_path, config, "settling",
                        next_acquisition_at_utc=None,
                        applied_exposure_us=exposure_us,
                        next_exposure_us=exposure_us,
                        **retained,
                    )
                    settling = settle_exposure(
                        config, recorder.capture_attempt, exposure_us
                    )
                    exposure_us = settling["selected_exposure_us"]
                    result = record_observation(
                        config, recorder.capture_attempt, exposure_us,
                        scheduled_for_utc=scheduled,
                        exposure_settling=settling,
                    )
                    try:
                        _publish_recorded_preview(config, result)
                    except Exception:
                        logger.exception(
                            "Could not publish diagnostic preview for completed observation %s",
                            result["manifest"]["observation_id"],
                        )
                    exposure_us = result["next_exposure_us"]
                    manifest = result["manifest"]
                    append_observation(config, manifest)
                    retained = {
                        "last_acquisition_at_utc": manifest["completed_at_utc"],
                        "last_observation_id": manifest["observation_id"],
                        "last_observation_relative_path": str(
                            result["path"].relative_to(config["storage"]["data_root"])
                        ),
                        "last_attempt_state": "complete",
                        "last_error": None,
                        "failed_observation_relative_path": None,
                    }
                    _publish_state(
                        state_path, config, "waiting" if not once else "complete",
                        next_acquisition_at_utc=None,
                        applied_exposure_us=manifest["capture"]["exposure_requested_us"],
                        next_exposure_us=exposure_us,
                        **retained,
                    )
                except ObservationCaptureError as error:
                    logger.exception("Observation failed; partial bundle retained at %s", error.path)
                    try:
                        append_failure(
                            config,
                            json.loads((error.path / "failure.json").read_text()),
                        )
                    except Exception:
                        logger.exception(
                            "Could not update recording summary for %s", error.path
                        )
                    retained.update({
                        "last_attempt_state": "failed",
                        "last_error": str(error),
                        "failed_observation_relative_path": str(
                            error.path.relative_to(config["storage"]["data_root"])
                        ),
                    })
                    _publish_state(
                        state_path, config, "failed",
                        next_acquisition_at_utc=None,
                        applied_exposure_us=exposure_us,
                        next_exposure_us=exposure_us,
                        **retained,
                    )
            if once:
                return
    _publish_state(
        state_path, config, "stopped",
        next_acquisition_at_utc=None,
        applied_exposure_us=exposure_us,
        next_exposure_us=exposure_us,
        **retained,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true", help="capture one observation immediately")
    args = parser.parse_args()
    configure()
    config = load_config(args.config)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    run(config, stop, once=args.once)


if __name__ == "__main__":
    main()
