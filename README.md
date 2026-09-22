# polstation

Python scaffold for a Raspberry Pi 5 sky-polarization instrument intended for a
year-long unattended deployment. **This is not field-ready software.** It does
not acquire images, communicate with hardware, synchronize cameras, or calculate
polarization. Its running acquisition process only publishes scaffold health.

Planned hardware: three Allied Vision Mako G-223B PoE cameras, a BME280 over I2C,
and an EPEVER Tracer 2210AN over USB-RS485/Modbus RTU. Camera serials, polarizer
angles, triggering, calibration, and bus parameters require commissioning.

## Local development

Python 3.11 or later:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
polstation-check-config --config config/default.yaml
polstation-acquisition --config config/default.yaml --once
polstation-acquisition --config config/default.yaml
```

In a second activated terminal:

```sh
polstation-dashboard --config config/default.yaml
```

Visit http://127.0.0.1:8000. Status explicitly reports `hardware_ready: false`.
The dashboard reads a shared status file; it does not control acquisition.
Missing, stale, stopped, or low-disk status produces HTTP 503 at `/api/status`.
HTTP 200 indicates scaffold liveness only.

Configuration files are complete standalone YAML documents, not overlays.
Relative storage paths resolve against the configuration file directory.
`config/default.yaml` is for local development; `config/example_field_config.yaml`
is a deployment template. There are no camera SDK, I2C, or Modbus dependencies.

## Repository and deployment

Code lives under `src/polstation/`; `tests/` is hardware-independent.
`deploy/systemd/` contains separate acquisition and dashboard service templates.

- [Architecture](docs/architecture.md)
- [Data and provenance](docs/data-format.md)
- [Calibration](docs/calibration.md)
- [Local → GitHub → Pi workflow](docs/deployment.md)
- [Operations and recovery](docs/operations.md)

Keep raw images, normal experimental data, logs, local configuration and large
calibration arrays outside Git. Small reviewed calibration metadata and procedures
may be tracked. Repository visibility is managed on GitHub; this scaffold does
not verify or change its visibility.
