"""Load a complete YAML configuration without implicit environment overrides."""
import argparse
import math
from pathlib import Path
import yaml


DEFAULT_CAMERA_PREVIEW = {
    "exposure_mode": "shared_auto",
    "stream_bytes_per_second": None,
    "initial_exposure_us": 15000,
    "minimum_exposure_us": 100,
    "maximum_exposure_us": 500000,
    "brightness_percentile": 99,
    "target_brightness_dn": 180,
    "brightness_tolerance_dn": 10,
    "maximum_step_factor": 2,
}

DEFAULT_POLARIZATION_PREVIEW = {"instrument_matrix": None}

DEFAULT_OBSERVATION_CAPTURE = {
    "interval_seconds": 600,
    "exposure_mode": "shared_auto",
    "initial_exposure_us": 15000,
    "minimum_exposure_us": 100,
    "maximum_exposure_us": 120000000,
    "brightness_percentile": 99,
    "target_brightness_dn": 2880,
    "brightness_tolerance_dn": 160,
    "maximum_step_factor": 2,
    "timeout_margin_seconds": 10,
    "maximum_capture_attempts": 3,
    "maximum_exposure_settling_attempts": 24,
    "maximum_exposure_settling_seconds": 480,
    "stream_bytes_per_second": None,
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
        camera.setdefault("preview_relative_gain", None)
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
    camera_preview.setdefault("stream_bytes_per_second", None)
    missing_preview = set(DEFAULT_CAMERA_PREVIEW) - set(camera_preview)
    if missing_preview:
        raise ValueError(
            "camera_preview is missing: " + ", ".join(sorted(missing_preview))
        )
    if camera_preview["exposure_mode"] not in ("fixed", "shared_auto"):
        raise ValueError("camera preview exposure_mode must be fixed or shared_auto")
    stream_limit = camera_preview["stream_bytes_per_second"]
    if (stream_limit is not None
            and (type(stream_limit) is not int or stream_limit <= 0)):
        raise ValueError(
            "camera_preview.stream_bytes_per_second must be a positive integer or null"
        )
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
    observation_capture = config.setdefault(
        "observation_capture", DEFAULT_OBSERVATION_CAPTURE.copy()
    )
    if not isinstance(observation_capture, dict):
        raise ValueError("observation_capture must be a mapping")
    for name, value in DEFAULT_OBSERVATION_CAPTURE.items():
        observation_capture.setdefault(name, value)
    if observation_capture["exposure_mode"] not in ("fixed", "shared_auto"):
        raise ValueError(
            "observation capture exposure_mode must be fixed or shared_auto"
        )
    for name in (
        "initial_exposure_us", "minimum_exposure_us", "maximum_exposure_us",
        "brightness_percentile", "target_brightness_dn", "maximum_step_factor",
        "timeout_margin_seconds",
    ):
        positive(observation_capture[name], f"observation_capture.{name}")
    for name in (
        "interval_seconds", "maximum_capture_attempts",
        "maximum_exposure_settling_attempts",
    ):
        value = observation_capture[name]
        if type(value) is not int or value <= 0:
            raise ValueError(f"observation_capture.{name} must be a positive integer")
    positive(
        observation_capture["maximum_exposure_settling_seconds"],
        "observation_capture.maximum_exposure_settling_seconds",
    )
    if not (
        observation_capture["minimum_exposure_us"]
        <= observation_capture["initial_exposure_us"]
        <= observation_capture["maximum_exposure_us"]
    ):
        raise ValueError(
            "observation capture initial exposure must be within its limits"
        )
    if observation_capture["maximum_exposure_us"] > 120_000_000:
        raise ValueError("observation capture maximum exposure must not exceed 120 seconds")
    if observation_capture["brightness_percentile"] > 100:
        raise ValueError("observation capture brightness percentile must not exceed 100")
    if observation_capture["target_brightness_dn"] > 4095:
        raise ValueError("observation capture target brightness must not exceed 4095 DN")
    tolerance = observation_capture["brightness_tolerance_dn"]
    if (isinstance(tolerance, bool) or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance) or tolerance < 0):
        raise ValueError(
            "observation_capture.brightness_tolerance_dn must be finite and nonnegative"
        )
    if tolerance >= observation_capture["target_brightness_dn"]:
        raise ValueError(
            "observation capture brightness tolerance must be below its target"
        )
    if observation_capture["maximum_step_factor"] <= 1:
        raise ValueError("observation capture maximum step factor must exceed one")
    stream_limit = observation_capture["stream_bytes_per_second"]
    if (stream_limit is not None
            and (type(stream_limit) is not int or stream_limit <= 0)):
        raise ValueError(
            "observation_capture.stream_bytes_per_second must be a positive integer or null"
        )
    polarization_preview = config.setdefault(
        "polarization_preview", DEFAULT_POLARIZATION_PREVIEW.copy()
    )
    if not isinstance(polarization_preview, dict):
        raise ValueError("polarization_preview must be a mapping")
    matrix_calibration = polarization_preview.get("instrument_matrix")
    if matrix_calibration is not None:
        if not isinstance(matrix_calibration, dict):
            raise ValueError("polarization_preview.instrument_matrix must be a mapping or null")
        required = {"camera_order", "response_matrix", "sensor_aop_offset_deg", "dark_model"}
        missing = required - set(matrix_calibration)
        if missing:
            raise ValueError("instrument matrix is missing: " + ", ".join(sorted(missing)))
        if matrix_calibration["camera_order"] != ids:
            raise ValueError("instrument matrix camera_order must exactly match configured cameras")
        response = matrix_calibration["response_matrix"]
        if (not isinstance(response, list) or len(response) != 3
                or any(not isinstance(row, list) or len(row) != 3 for row in response)
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) for row in response for value in row)):
            raise ValueError("instrument response_matrix must be a finite 3x3 array")
        a, b, c = response[0]
        d, e, f = response[1]
        g, h, i = response[2]
        determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
        if abs(determinant) < 1e-12:
            raise ValueError("instrument response_matrix must be nonsingular")
        offset = matrix_calibration["sensor_aop_offset_deg"]
        if (isinstance(offset, bool) or not isinstance(offset, (int, float))
                or not math.isfinite(offset)):
            raise ValueError("instrument matrix sensor_aop_offset_deg must be finite")
        dark = matrix_calibration["dark_model"]
        if not isinstance(dark, dict):
            raise ValueError("instrument matrix dark_model must be a mapping")
        exposures = dark.get("exposure_ms")
        values = dark.get("roi_median_mono12_by_camera")
        divisor = dark.get("mono12_to_mono8_divisor")
        if (not isinstance(exposures, list) or len(exposures) < 2
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(value) or value <= 0 for value in exposures)
                or any(left >= right for left, right in zip(exposures, exposures[1:]))):
            raise ValueError("instrument dark exposure_ms must be strictly increasing positive numbers")
        if not isinstance(values, dict) or set(values) != set(ids):
            raise ValueError("instrument dark curves must exactly match configured camera IDs")
        for camera_id in ids:
            curve = values[camera_id]
            if (not isinstance(curve, list) or len(curve) != len(exposures)
                    or any(isinstance(value, bool) or not isinstance(value, (int, float))
                           or not math.isfinite(value) or value < 0 for value in curve)):
                raise ValueError(f"instrument dark curve for {camera_id} is invalid")
        positive(divisor, "instrument dark mono12_to_mono8_divisor")
        minimum_supported = dark.get("minimum_supported_exposure_ms", exposures[0])
        positive(minimum_supported, "instrument dark minimum_supported_exposure_ms")
        if minimum_supported > exposures[0]:
            raise ValueError(
                "instrument dark minimum_supported_exposure_ms must not exceed "
                "the first measured exposure"
            )
        low_exposure_policy = dark.get("below_measured_policy")
        if minimum_supported < exposures[0]:
            if low_exposure_policy != "hold_first_offset":
                raise ValueError(
                    "instrument dark exposures below the first measured point "
                    "require below_measured_policy: hold_first_offset"
                )
        elif low_exposure_policy is not None:
            raise ValueError(
                "instrument dark below_measured_policy requires a supported "
                "exposure below the first measured point"
            )
        if not config["provenance"].get("calibration_id"):
            raise ValueError("instrument matrix requires provenance.calibration_id")
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
    preview_gains = [camera["preview_relative_gain"] for camera in cameras]
    if any(gain is not None for gain in preview_gains):
        if any(gain is None for gain in preview_gains):
            raise ValueError("preview relative gains must be configured for all three cameras")
        for gain in preview_gains:
            positive(gain, "camera preview_relative_gain")
        if not provenance["calibration_id"]:
            raise ValueError("preview relative gains require provenance.calibration_id")
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
