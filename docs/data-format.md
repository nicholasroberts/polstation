# Data and provenance

The timed observation recorder implements version-1 immutable three-camera
bundles under the configured `storage.data_root`:

```text
/var/lib/polstation/data/YYYY/MM/DD/<observation-id>/
    raw/camera-01.attempt-001.mono12.raw
    raw/camera-02.attempt-001.mono12.raw
    raw/camera-03.attempt-001.mono12.raw
    [raw files from later bounded attempts]
    config.json
    manifest.json
```

Allocate observation IDs uniquely. Write raw images without modifying their
pixels or overwriting existing files. Each `.raw` file is the original Vimba
Mono12 buffer: little-endian 12-bit values stored in 16-bit words, with no
linearisation, dark correction or preview conversion. Width, height, packing,
byte count and SHA-256 are in the manifest. Raw files and the effective
configuration are flushed before `manifest.json` is published as the final
completion marker. Readers must ignore directories without that marker as
complete observations. Exhausted retries instead publish `failure.json`; all
returned attempt buffers remain available for investigation. Nothing in this
path automatically deletes or overwrites raw data.

The JSON writer uses a temporary file, fsync, and same-directory atomic
publication. Immutable publication refuses to overwrite an existing manifest;
replace mode is reserved for transient health. Power-loss guarantees depend on
the filesystem and storage hardware and require testing on the Pi.

Each completed version-1 observation records:

- Software package version, full Git commit, release tag, calibration ID, and
  SHA-256 of the effective configuration (canonical sorted JSON).
- Observation ID, start time, and per-camera UTC capture time, timestamp source,
  optional device clock value, exposure, gain, pixel format, path and SHA-256.
- The latest diagnostic sensor snapshot read at observation start, including its
  own sample timestamps and an explicit statement that frame association remains
  unvalidated.
- Synchronization state, initially `unverified`.
- Every bounded capture attempt and the selected all-complete three-camera
  attempt. A mixed set of frames from different attempts is never promoted into
  one completed observation.
- The exposure controller mode, central-ROI percentile, next exposure and an
  explicit `validated_for_scientific_use: false` flag.

Three timestamps do not establish simultaneous exposure. Triggering, clock
mapping, allowed skew and sensor-to-frame association must be specified and
measured during hardware integration. Missing/invalid samples must remain
explicit. Derived polarization products must refer back to immutable raw data
and record their own processing software and calibration provenance.

Null provenance fields mean unknown, not a verified release. For field datasets,
record the actual immutable release commit and calibration asset checksums.
The replaceable `observation-recorder.json` file in the state root is operational
status, not scientific data. The dashboard uses it for recorder state, last
completed acquisition and next scheduled acquisition. The scientific record is
only a bundle with its immutable `manifest.json` and referenced raw files.
