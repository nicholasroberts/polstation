"""Bounded, preview-only Vimba capture and file-backed dashboard snapshots."""

import argparse
import base64
import binascii
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import signal
import struct
import threading
import time
import zlib

from polstation.config import load_config
from polstation.logging.setup import configure
from polstation.storage.layout import prepare
from polstation.storage.manifests import write_json

logger = logging.getLogger(__name__)


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)


def mono8_preview_png(buffer, width, height, *, max_width=640, max_height=400):
    """Encode a bounded downsampled Mono8 frame as a browser-native PNG."""
    if width <= 0 or height <= 0:
        raise ValueError("frame dimensions must be positive")
    pixels = memoryview(buffer).cast("B")
    if len(pixels) < width * height:
        raise ValueError("frame buffer is smaller than its dimensions")
    step = max(1, (width + max_width - 1) // max_width, (height + max_height - 1) // max_height)
    sampled_width = (width + step - 1) // step
    sampled_height = (height + step - 1) // step
    rows = []
    for y in range(0, height, step):
        start = y * width
        rows.append(b"\0" + bytes(pixels[start:start + width:step]))
    header = struct.pack(">IIBBBBB", sampled_width, sampled_height, 8, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(b"".join(rows), 3)) + _png_chunk(b"IEND", b"")


def _read_feature(camera, *names):
    for name in names:
        try:
            return camera.get_feature_by_name(name).get()
        except Exception:
            pass
    return None


class FilePreviewSource:
    """Read the atomic latest-preview file without importing or opening Vimba."""

    mode = "hardware-preview"

    def __init__(self, config):
        self.path = Path(config["storage"]["state_root"]) / "camera-previews.json"
        self.stale_after_seconds = config["dashboard"]["stale_after_seconds"]

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
            return value
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
            return {"schema_version": 1, "mode": self.mode, "hardware_ready": False,
                    "recording": False, "synchronization": "unverified",
                    "error": str(error), "cameras": []}


def run_hardware_preview(config, stop, *, interval=1.0, timeout_ms=5000):
    """Publish sequential real-camera previews; never write observations."""
    try:
        from vmbpy import FrameStatus, PixelFormat, VmbSystem
    except ImportError as error:
        raise RuntimeError("VmbPy is required for hardware preview mode") from error

    prepare(config)
    output = Path(config["storage"]["state_root"]) / "camera-previews.json"
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
                    original = (camera, packet, packet.get(), camera.get_pixel_format(), trigger, trigger.get())
                    originals.append(original)
                    packet.set(1500)
                    camera.set_pixel_format(PixelFormat.Mono8)
                    trigger.set("Off")

                while not stop.is_set():
                    cycle_started = time.monotonic()
                    snapshots = []
                    for camera in opened:
                        camera_id = camera.get_id()
                        try:
                            frame = camera.get_frame(timeout_ms=timeout_ms)
                            if frame.get_status() != FrameStatus.Complete:
                                raise RuntimeError(f"incomplete frame: {frame.get_status()}")
                            width, height = frame.get_width(), frame.get_height()
                            encoded = base64.b64encode(mono8_preview_png(bytes(frame.get_buffer()), width, height)).decode("ascii")
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
                    write_json(output, {"schema_version": 1, "mode": "hardware-preview",
                                       "hardware_ready": all(item["state"] == "live" for item in snapshots),
                                       "recording": False, "synchronization": "unverified",
                                       "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                                       "cameras": snapshots}, replace=True)
                    stop.wait(max(0.0, interval - (time.monotonic() - cycle_started)))
            finally:
                for camera, packet, packet_value, pixel_format, trigger, trigger_value in reversed(originals):
                    try:
                        trigger.set(trigger_value)
                        camera.set_pixel_format(pixel_format)
                        packet.set(packet_value)
                    except Exception:
                        logger.exception("Could not restore preview settings for %s", camera.get_id())


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
