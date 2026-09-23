# Working on polstation

## Purpose and scope

Build a Raspberry Pi 5 sky-polarization instrument intended to operate unattended
for one year. Prioritize scientific correctness, preservation of observations,
and recovery from faults. Work in small, reviewable steps within the requested
scope. Distinguish implemented behavior from planned or hardware-unverified work.

Target hardware: three Allied Vision Mako G-223B PoE cameras, BME280 over I2C,
and EPEVER Tracer 2210AN over USB-RS485/Modbus. Verify SDK/platform compatibility
and device parameters before relying on them; do not invent commissioning values.

## Architecture and access

- Keep Python code under `src/polstation/` and respect its package boundaries.
- Acquisition runs headless and independently of the dashboard. Closing the
  browser, SSH tunnel, or dashboard must not stop acquisition.
- Hardware connections belong to acquisition adapters, never browser request
  handlers. Serve previews from bounded latest-frame snapshots.
- Keep acquisition and dashboard as separate systemd services.
- Bind the dashboard to loopback for SSH-tunnel access through the external
  Ethernet service port and TSW101 network. Keep deployment-specific addresses
  in configuration rather than code.

## Scientific data and calibration

- Preserve original raw image pixels and bit depth. Apply preview conversion,
  linearisation, dark correction, and polarization processing to separate
  derived products. Never silently overwrite raw observations or calibration
  assets, or introduce automatic raw-data deletion.
- Record software version, Git commit, configuration identity, calibration
  identity, and relevant camera settings with observations. Derived products
  must retain links to their raw inputs and processing provenance.
- Record timestamp sources and sensor sample times explicitly. Do not claim
  synchronized exposure from matching timestamps alone; validate timing.
- Document calibration equations, units, assumptions, validity ranges, and
  correction order. When importing the earlier Ubuntu implementation, establish
  reference inputs and outputs before altering its scientific methods.
- Keep experimental data, credentials, local field configuration, and large
  calibration arrays out of Git. Small reviewed calibration metadata and
  procedures may be tracked; identify external assets with stable IDs and hashes.

## Reliability and demo behavior

- Keep memory use, frame queues, retry delays, and log retention bounded.
  Preserve graceful shutdown and report failures rather than hiding them.
- Show stale, missing, disconnected, and invalid data explicitly. Never present
  a retained frame as live or a simulated value as a hardware measurement.
- Demo mode must be explicit, clearly labelled, runnable without hardware SDKs,
  and separate from scientific recording. Do not write demo frames as observations.
- Preserve the established dashboard visual style when extending it. Make
  functional status understandable without relying on color alone.

## Development and verification

Use Python 3.11+ and the repository virtual environment. From the repository root:

```sh
python3 -m venv .venv                  # First setup only
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
polstation-check-config --config config/default.yaml
polstation-dashboard --config config/default.yaml --demo
```

Tests are hardware-independent; HTTP tests bind temporary loopback ports.
Run checks appropriate to the change. For dashboard changes, verify the affected
behavior in a browser. Clearly distinguish local tests from tests on the Pi or
real cameras; successful simulation is not hardware validation.

## Documentation and continuity

- Keep the README detailed, accurate, and practical, including setup commands
  and the distinction between implemented and planned features.
- Record important design decisions and unresolved scientific assumptions in
  the relevant repository documentation; do not rely on prior chat history.
- Consult `docs/architecture.md` for service boundaries,
  `docs/data-format.md` for storage and provenance, `docs/calibration.md` for
  calibration, and `docs/deployment.md` / `docs/operations.md` for Pi operation
  when the task touches those areas.
- Keep this file concise and durable. Put detailed methods, changing project
  status, and commissioning results in `docs/` rather than duplicating them here.
