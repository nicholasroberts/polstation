"""Bounded, read-only BME280 and EPEVER latest-value publisher."""

import argparse
from datetime import datetime, timezone
import logging
from pathlib import Path
import signal
import threading
import time

from polstation.config import load_config
from polstation.logging.setup import configure
from polstation.storage.layout import prepare_state
from polstation.storage.manifests import write_json

logger = logging.getLogger(__name__)


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _u32(low, high):
    return (high << 16) | low


def _s16(value):
    return value - 0x10000 if value & 0x8000 else value


def _s32(low, high):
    value = _u32(low, high)
    return value - 0x100000000 if value & 0x80000000 else value


def sample_bme280(settings):
    """Read one compensated BME280 sample without retaining the bus handle."""
    import bme280
    import smbus2

    bus_number = settings.get("bus")
    address = settings.get("address")
    if type(bus_number) is not int or type(address) is not int:
        raise ValueError("BME280 bus and address are not configured")
    bus = smbus2.SMBus(bus_number)
    try:
        calibration = bme280.load_calibration_params(bus, address)
        sample = bme280.sample(bus, address, calibration)
        return {
            "temperature_c": round(float(sample.temperature), 3),
            "pressure_hpa": round(float(sample.pressure), 3),
            "humidity_percent": round(float(sample.humidity), 3),
        }
    finally:
        bus.close()


def _decode_epever(realtime, load_temp, soc_remote, status, statistics, battery_live):
    charging_stages = {0: "not charging", 1: "float", 2: "boost", 3: "equalization"}
    input_states = {0: "normal", 1: "no PV input", 2: "PV over-voltage", 3: "PV input error"}
    battery_states = {0: "normal", 1: "over-voltage", 2: "under-voltage",
                      3: "low-voltage disconnect", 4: "fault"}
    battery_status, charging_status, load_status = status
    return {
        "pv_voltage_v": realtime[0] / 100,
        "pv_current_a": realtime[1] / 100,
        "pv_power_w": _u32(realtime[2], realtime[3]) / 100,
        "battery_charge_voltage_v": realtime[4] / 100,
        "battery_charge_current_a": realtime[5] / 100,
        "battery_charge_power_w": _u32(realtime[6], realtime[7]) / 100,
        "load_voltage_v": load_temp[0] / 100,
        "load_current_a": load_temp[1] / 100,
        "load_power_w": _u32(load_temp[2], load_temp[3]) / 100,
        "battery_temperature_c": _s16(load_temp[4]) / 100,
        "controller_temperature_c": _s16(load_temp[5]) / 100,
        "battery_soc_percent": soc_remote[0],
        # Zero is retained as the controller's raw result, but is not displayed
        # as a valid remote-probe temperature by the dashboard.
        "remote_battery_temperature_c": _s16(soc_remote[1]) / 100,
        "battery_voltage_v": battery_live[0] / 100,
        "battery_net_current_a": _s32(battery_live[1], battery_live[2]) / 100,
        "battery_voltage_state": battery_states.get(battery_status & 0x0F, "unknown"),
        "charging_stage": charging_stages.get((charging_status >> 2) & 0x03, "unknown"),
        "pv_input_state": input_states.get((charging_status >> 14) & 0x03, "unknown"),
        "controller_running": bool(charging_status & 0x01),
        "controller_fault": bool(charging_status & 0x02),
        "load_running": bool(load_status & 0x01),
        "battery_status_raw": battery_status,
        "charging_status_raw": charging_status,
        "load_status_raw": load_status,
        "consumed_today_kwh": _u32(statistics[4], statistics[5]) / 100,
        "consumed_total_kwh": _u32(statistics[10], statistics[11]) / 100,
        "generated_today_kwh": _u32(statistics[12], statistics[13]) / 100,
        "generated_total_kwh": _u32(statistics[18], statistics[19]) / 100,
    }


def sample_epever(settings):
    """Read documented EPEVER input registers; never write settings or coils."""
    import minimalmodbus

    required = ("device", "slave_address", "baudrate", "parity", "stopbits")
    if any(settings.get(name) is None for name in required):
        raise ValueError("EPEVER serial settings are not configured")
    meter = minimalmodbus.Instrument(settings["device"], settings["slave_address"])
    meter.mode = minimalmodbus.MODE_RTU
    meter.serial.baudrate = settings["baudrate"]
    meter.serial.bytesize = 8
    meter.serial.parity = settings["parity"]
    meter.serial.stopbits = settings["stopbits"]
    meter.serial.timeout = 1.0
    meter.clear_buffers_before_each_transaction = True

    def read(address, count):
        return meter.read_registers(address, count, functioncode=4)

    try:
        return _decode_epever(
            read(0x3100, 8),
            read(0x310C, 6),
            read(0x311A, 2),
            read(0x3200, 3),
            read(0x3300, 20),
            read(0x331A, 3),
        )
    finally:
        meter.serial.close()


def sensor_snapshot(config, samplers=None):
    samplers = samplers or {"bme280": sample_bme280, "epever": sample_epever}
    sensors = {}
    for name, sampler in samplers.items():
        started = time.monotonic()
        try:
            values = sampler(config["sensors"][name])
            sensors[name] = {
                "state": "live",
                "sampled_at_utc": _utc_now(),
                "sample_duration_ms": round((time.monotonic() - started) * 1000, 1),
                "values": values,
            }
        except Exception as error:
            logger.exception("Sensor sample failed for %s", name)
            sensors[name] = {
                "state": "unavailable",
                "sampled_at_utc": None,
                "sample_duration_ms": round((time.monotonic() - started) * 1000, 1),
                "error": str(error),
                "values": {},
            }
    return {
        "schema_version": 1,
        "mode": "hardware-sensors",
        "updated_at_utc": _utc_now(),
        "sensors": sensors,
    }


def run_sensor_preview(config, stop, *, interval=5.0, samplers=None):
    prepare_state(config)
    output = Path(config["storage"]["state_root"]) / "sensor-preview.json"
    while not stop.is_set():
        cycle_started = time.monotonic()
        write_json(output, sensor_snapshot(config, samplers), replace=True)
        stop.wait(max(0.0, interval - (time.monotonic() - cycle_started)))


def main():
    parser = argparse.ArgumentParser(description="Publish bounded read-only sensor telemetry")
    parser.add_argument("--config", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    configure()
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    run_sensor_preview(load_config(args.config), stop, interval=args.interval)


if __name__ == "__main__":
    main()
