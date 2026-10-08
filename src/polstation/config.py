"""Load a complete YAML configuration without implicit environment overrides."""
import argparse
import math
from pathlib import Path
import yaml


DEFAULT_CAMERA_PREVIEW = {
    "exposure_mode": "shared_auto",
    "initial_exposure_us": 15000,
    "minimum_exposure_us": 100,
    "maximum_exposure_us": 500000,
    "brightness_percentile": 99,
    "target_brightness_dn": 180,
    "brightness_tolerance_dn": 10,
    "maximum_step_factor": 2,
}


def positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")


def load_config(path):
    config_path = Path(path).resolve()
    config = yaml.safe_load(config_path.read_text())
    if not isinstance(config, dict):
        raise ValueError("configuration must be a mapping")
    if config.get("mode") != "scaffold":
        raise ValueError("only scaffold mode is implemented")
    cameras = config["cameras"]
    if not isinstance(cameras, list) or len(cameras) != 3:
        raise ValueError("exactly three camera slots are required")
    ids = [camera["id"] for camera in cameras]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != 3:
        raise ValueError("camera IDs must be unique nonempty strings")
    for camera in cameras:
        if camera["model"] != "Allied Vision Mako G-223B":
            raise ValueError("unexpected camera model")
    angles = [camera["polarizer_angle_deg"] for camera in cameras]
    if any(angle is not None for angle in angles):
        if any(isinstance(angle, bool) for angle in angles) or set(angles) != {0, 45, 90}:
            raise ValueError("camera polarizer angles must be all null or exactly 0, 45, and 90 degrees")
    for name in ("heartbeat_seconds", "retry_initial_seconds", "retry_max_seconds"):
        positive(config["acquisition"][name], name)
    if config["acquisition"]["retry_initial_seconds"] > config["acquisition"]["retry_max_seconds"]:
        raise ValueError("initial retry must not exceed maximum retry")
    camera_preview = config.setdefault("camera_preview", DEFAULT_CAMERA_PREVIEW.copy())
    if not isinstance(camera_preview, dict):
        raise ValueError("camera_preview must be a mapping")
    missing_preview = set(DEFAULT_CAMERA_PREVIEW) - set(camera_preview)
    if missing_preview:
        raise ValueError(
            "camera_preview is missing: " + ", ".join(sorted(missing_preview))
        )
    if camera_preview["exposure_mode"] not in ("fixed", "shared_auto"):
        raise ValueError("camera preview exposure_mode must be fixed or shared_auto")
    for name in (
        "initial_exposure_us", "minimum_exposure_us", "maximum_exposure_us",
        "brightness_percentile", "target_brightness_dn", "maximum_step_factor",
    ):
        positive(camera_preview[name], f"camera_preview.{name}")
    tolerance = camera_preview["brightness_tolerance_dn"]
    if (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance) or tolerance < 0):
        raise ValueError("camera_preview.brightness_tolerance_dn must be finite and nonnegative")
    if not camera_preview["minimum_exposure_us"] <= camera_preview["initial_exposure_us"] <= camera_preview["maximum_exposure_us"]:
        raise ValueError("camera preview initial exposure must be within its limits")
    if camera_preview["brightness_percentile"] > 100:
        raise ValueError("camera preview brightness percentile must not exceed 100")
    if camera_preview["target_brightness_dn"] > 255:
        raise ValueError("camera preview target brightness must not exceed 255 DN")
    if tolerance >= camera_preview["target_brightness_dn"]:
        raise ValueError("camera preview brightness tolerance must be below its target")
    if camera_preview["maximum_step_factor"] <= 1:
        raise ValueError("camera preview maximum step factor must exceed one")
    positive(config["storage"]["minimum_free_bytes"], "minimum_free_bytes")
    positive(config["dashboard"]["stale_after_seconds"], "stale_after_seconds")
    if config["dashboard"]["host"] != "127.0.0.1":
        raise ValueError("dashboard must bind to 127.0.0.1; use an SSH tunnel")
    port = config["dashboard"]["port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("dashboard port must be an integer between 1 and 65535")
    if config["sensors"]["bme280"]["interface"] != "i2c":
        raise ValueError("BME280 interface must be i2c")
    bme280 = config["sensors"]["bme280"]
    if bme280["bus"] is not None or bme280["address"] is not None:
        if type(bme280["bus"]) is not int or bme280["bus"] < 0:
            raise ValueError("BME280 bus must be a nonnegative integer")
        if type(bme280["address"]) is not int or not 0x03 <= bme280["address"] <= 0x77:
            raise ValueError("BME280 address must be a valid 7-bit I2C address")
    if config["sensors"]["epever"]["interface"] != "usb-rs485-modbus-rtu":
        raise ValueError("EPEVER interface must be usb-rs485-modbus-rtu")
    epever = config["sensors"]["epever"]
    serial_names = ("device", "slave_address", "baudrate", "parity", "stopbits")
    serial_values = [epever[name] for name in serial_names]
    if any(value is not None for value in serial_values):
        if any(value is None for value in serial_values):
            raise ValueError("EPEVER serial settings must be configured together")
        if not isinstance(epever["device"], str) or not epever["device"].startswith("/dev/serial/by-id/"):
            raise ValueError("EPEVER device must use a stable /dev/serial/by-id path")
        if type(epever["slave_address"]) is not int or not 1 <= epever["slave_address"] <= 247:
            raise ValueError("EPEVER slave address must be an integer from 1 to 247")
        if type(epever["baudrate"]) is not int or epever["baudrate"] <= 0:
            raise ValueError("EPEVER baudrate must be a positive integer")
        if epever["parity"] not in ("N", "E", "O") or epever["stopbits"] not in (1, 2):
            raise ValueError("EPEVER parity/stopbits are invalid")
    provenance = config["provenance"]
    for key in ("git_commit", "release_tag", "calibration_id"):
        if provenance[key] is not None and not isinstance(provenance[key], str):
            raise ValueError(f"{key} must be a string or null")
    for key in ("data_root", "state_root"):
        path_value = Path(config["storage"][key]).expanduser()
        config["storage"][key] = str((config_path.parent / path_value).resolve())
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    load_config(args.config)
    print("Configuration valid (scaffold mode; hardware settings are not verified).")


if __name__ == "__main__":
    main()
