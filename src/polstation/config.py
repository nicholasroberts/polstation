"""Load a complete YAML configuration without implicit environment overrides."""
import argparse
import math
from pathlib import Path
import yaml


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
    for name in ("heartbeat_seconds", "retry_initial_seconds", "retry_max_seconds"):
        positive(config["acquisition"][name], name)
    if config["acquisition"]["retry_initial_seconds"] > config["acquisition"]["retry_max_seconds"]:
        raise ValueError("initial retry must not exceed maximum retry")
    positive(config["storage"]["minimum_free_bytes"], "minimum_free_bytes")
    positive(config["dashboard"]["stale_after_seconds"], "stale_after_seconds")
    if config["dashboard"]["host"] != "127.0.0.1":
        raise ValueError("dashboard must bind to 127.0.0.1; use an SSH tunnel")
    port = config["dashboard"]["port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("dashboard port must be an integer between 1 and 65535")
    if config["sensors"]["bme280"]["interface"] != "i2c":
        raise ValueError("BME280 interface must be i2c")
    if config["sensors"]["epever"]["interface"] != "usb-rs485-modbus-rtu":
        raise ValueError("EPEVER interface must be usb-rs485-modbus-rtu")
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
