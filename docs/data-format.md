# Data and provenance

The scaffold defines metadata dataclasses; it does not write raw images or create
observation bundles. Future acquisition must implement this layout and protocol:

```text
/var/lib/polstation/data/YYYY/MM/DD/<observation-id>/
    raw/<camera-id>.<lossless-raw-format>
    config.json
    manifest.json
```

Allocate observation IDs uniquely. Write raw images without modifying their
pixels or overwriting existing files. Preserve camera pixel format and original
bit depth; choose a lossless container after SDK evaluation. Flush and fsync raw
files and the effective configuration snapshot before publishing `manifest.json`
as the final completion marker. Readers must ignore directories without that
marker. On restart, retain and report incomplete bundles for investigation;
never overwrite or automatically delete them.

The JSON writer uses a temporary file, fsync, and same-directory atomic
publication. Immutable publication refuses to overwrite an existing manifest;
replace mode is reserved for transient health. Power-loss guarantees depend on
the filesystem and storage hardware and require testing on the Pi.

Each version-1 observation records:

- Software package version, full Git commit, release tag, calibration ID, and
  SHA-256 of the effective configuration (canonical sorted JSON).
- Observation ID, start time, and per-camera UTC capture time, timestamp source,
  optional device clock value, exposure, gain, pixel format, path and SHA-256.
- Sensor samples with their own UTC timestamps, values, units and status.
- Synchronization state, initially `unverified`.

Three timestamps do not establish simultaneous exposure. Triggering, clock
mapping, allowed skew and sensor-to-frame association must be specified and
measured during hardware integration. Missing/invalid samples must remain
explicit. Derived polarization products must refer back to immutable raw data
and record their own processing software and calibration provenance.

Null provenance fields mean unknown, not a verified release. For field datasets,
record the actual immutable release commit and calibration asset checksums.
The scaffold health snapshot includes provenance and config hash but creates no
scientific dataset. Configuration and dataclasses are initial contracts, not a
complete validated scientific serialization pipeline.
