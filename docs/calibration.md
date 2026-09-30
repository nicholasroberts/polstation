# Calibration plan

No scientific calibration or polarization product pipeline is implemented yet.
The hardware-preview producer includes a deliberately limited diagnostic
three-analyser calculation so camera orientation and scene response can be
inspected during commissioning.

## Diagnostic three-analyser preview

For matching preview pixels from analysers at 0°, 45°, and 90°, the preview uses:

```text
S0 = I0 + I90
Q  = I0 - I90
U  = 2 I45 - I0 - I90
DoLP = sqrt(Q² + U²) / S0
AoP  = 0.5 atan2(U, Q) mod 180°
```

`I` values are uncorrected Mono8 digital numbers after preview down-sampling.
DoLP is clipped to 0–1 solely for display. AoP is sensor-relative; it is undefined
where `S0` is zero or both `Q` and `U` are zero, and those pixels display black.
No arbitrary low-DoLP mask is applied. The doubled-angle Stokes direction is
halved exactly once to obtain AoP.

DoLP uses a fixed plasma 0–100% scale. AoP uses a fixed cyclic cmocean phase
0–180° scale, with 0° and 180° meeting at the same colour. The tables and their
upstream licences are stored with the package.

These maps combine sequential frames from separate cameras without spatial
registration, exposure synchronization, dark/flat correction, linearisation, or
cross-camera responsivity calibration. They are commissioning diagnostics, not
scientific measurements, and are not written as observations. Camera IDs and
their verified analyser angles belong in ignored local configuration.

Maintain calibration procedures and small reviewed JSON/CSV metadata in Git.
Store dark maps, flat fields, response arrays and other large assets on separate
instrument storage with backups. Git LFS is optional and is not configured here.

Each calibration should have a stable ID, creation time, camera serials, optical
configuration, polarizer angles, procedure version, acquisition conditions,
validity criteria, and SHA-256 hashes locating its external assets. Never silently
replace an asset under an existing ID. Record the calibration ID with every
future dataset and retain the assets for reproducibility.

Commissioning must establish dark/flat corrections, camera response, optical
alignment, polarizer orientations and timing error before deriving polarization.

## Earlier Ubuntu workflow

See [the legacy calibration review](legacy-calibration-review.md) for the
reviewed dark/response correction equations, Stokes calculations, false-colour
conventions, and issues to resolve before integrating hardware or methods.
This is a static review, not a validated port.
