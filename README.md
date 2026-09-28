# polstation

Python scaffold for a Raspberry Pi 5 sky-polarization instrument intended for a
year-long unattended deployment. **This is not field-ready software.** Its main
acquisition process remains a scaffold and does not yet record images or operate
sensors. A separate Pi-tested Vimba X diagnostic captures bounded Mono8 previews
and can calculate uncalibrated DoLP/AoP previews; it is not scientific acquisition.

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

## Try the three-camera demo on your Mac

No Pi, cameras, acquisition service, or additional dependencies are needed. From
this repository, after the local installation above:

```sh
. .venv/bin/activate
polstation-dashboard --config config/default.yaml --demo
```

Open **http://127.0.0.1:8000** in Safari or Chrome. Stop the server with `Ctrl+C`.
If port 8000 is already occupied by the scaffold dashboard, stop that process
first, or copy the configuration to an ignored `config/local-demo.yaml` and
change `dashboard.port` in that copy before launching with its path.

The demo shows three synthetic sky previews with simulated exposure, gain,
frame numbers, UTC timestamps and frame age. The prominent **DEMO — no cameras
connected** banner stays visible. These are illustrative graphics, not actual
Mako images, calibrated sky models or synchronized observations.

Use **Demo scenario** to switch between:

- **All cameras live:** all three simulated frames advance approximately once
  per second while the page is open.
- **Stale + disconnected:** camera 1 advances, camera 2 retains a deliberately
  old frozen frame with its growing age, and camera 3 has no preview.

Switching back restores all three simulated feeds. If the server stops or
requests fail, the page marks the previews unavailable and retains any last
image for context. It retries automatically. The displayed clock is laptop local
time; frame timestamps are UTC. Exposure and gain are labelled simulated even
when a camera is disconnected; they are not device readbacks.

Demo mode writes no images, scientific metadata, calibration data or health
files. It does not change the acquisition service or enable any hardware driver.
Without `--demo`, the original scaffold status page remains in use. The systemd
templates do not enable demo mode.

The read-only `/api/previews?scenario=live` endpoint returns in-memory snapshots
from a separate `DemoPreviewSource`; `scenario=faults` selects the fault example.
The simulator computes frames on request, with no capture worker or growing frame
queue. The dashboard only renders these snapshots.

## Diagnostic preview with three real cameras

An initial hardware-preview path has been verified on the Pi 5. It is a bounded
diagnostic, not scientific acquisition: the producer captures the three cameras
sequentially in Mono8, publishes replaceable latest-frame previews, and records
no observations. Frames are not synchronized, registered, or calibrated.

For the polarization diagnostic, use an ignored local configuration that maps
the three camera IDs to the physically verified analyser angles 0°, 45°, and
90°. Hardware IDs are intentionally not stored in this repository. When all
three mapped frames are available, the dashboard shows a DoLP map on a fixed
plasma 0–100% scale and a sensor-relative AoP map on a fixed cyclic cmocean phase
0–180° scale. The page labels both products as sequential, unregistered,
unsynchronized, and uncalibrated.

With the SDK-matched VmbPy environment active and all three cameras discovered:

```sh
polstation-camera-preview --config config/local-preview.yaml --interval 1
```

Run the read-only dashboard separately:

```sh
polstation-dashboard --config config/local-preview.yaml --hardware-preview
```

The dashboard continues to bind to Pi loopback. From the laptop, forward a local
port and browse to `http://127.0.0.1:8080`:

```sh
ssh -N -L 8080:127.0.0.1:8000 OPERATOR@ACTUAL_PI_ADDRESS
```

The producer temporarily selects a 1500-byte camera packet, Mono8, and free-run
triggering, and restores the preceding values on clean shutdown. Stop it with
`Ctrl+C`. Do not use this path as evidence of synchronized exposure or raw-data
preservation.

## Repository and deployment

Code lives under `src/polstation/`; `tests/` is hardware-independent.
`deploy/systemd/` contains separate acquisition and dashboard service templates.

- [Architecture](docs/architecture.md)
- [Data and provenance](docs/data-format.md)
- [Calibration](docs/calibration.md)
- [First SSH and Vimba X camera bring-up](docs/first-boot.md)
- [2026-09-28 Pi/Vimba X commissioning record](docs/commissioning/2026-09-28-pi5-vimbax-camera-bring-up.md)
- [Local → GitHub → Pi workflow](docs/deployment.md)
- [Operations and recovery](docs/operations.md)

Keep raw images, normal experimental data, logs, local configuration and large
calibration arrays outside Git. Small reviewed calibration metadata and procedures
may be tracked. Repository visibility is managed on GitHub; this scaffold does
not verify or change its visibility.
