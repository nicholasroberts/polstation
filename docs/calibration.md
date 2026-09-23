# Calibration plan

No calibration or polarization calculations are implemented yet.

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
