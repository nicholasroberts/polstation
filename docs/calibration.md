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

The preview can optionally apply one positive relative-sensitivity multiplier
per configured camera. For preview pixels, the implemented order is
`I'angle = preview_relative_gain * Iangle`, followed by the three-analyser Stokes
equations above. All three gains and `provenance.calibration_id` are required
together. This improves the commissioning display but does not make it a
scientific calibration: the preview still lacks exposure- and temperature-aware
dark subtraction, flat-field correction, spatial registration, and synchronized
exposures. The future scientific order is raw preservation, linearisation, dark
correction, flat/relative-response correction, registration, and then Stokes
processing.

The preview producer's auto-exposure is shared: it applies the same exposure to
all three cameras from the brightest configured preview percentile. Independent
camera auto-exposure is deliberately disabled because it would alter the analyser
ratios. Exposure changes between preview cycles, so the readback published with
each camera and the top-level exposure-control metadata must accompany any
interpretation. This bounded display controller is not a calibrated acquisition
exposure policy.

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

## Camera-linearity scouting capture

`polstation-camera-linearity` acquires a controlled Mono12 exposure sweep from
the three configured cameras. It writes every original frame buffer used by the
calculation, a CSV summary, a completion manifest with hashes and settings, and
three diagnostic plots: central-ROI median response with fitted straight lines,
residuals from those fits, and grouped boxplots of the central-ROI pixel
distribution. The camera order alternates between repeats to reduce monotonic
source-drift bias, but acquisition remains sequential and is labelled as such.
An incomplete GigE frame is rejected and retried up to three times. Successful
manifests record every rejected attempt and the attempt number of each retained
frame; exhaustion of the bounded retry still fails the capture explicitly.

The default ROI exactly reproduces the reviewed earlier program: a circle at
50% image width, 50% image height, with radius 60% of half the smaller image
dimension. This is the primary scientific region for the fisheye images. The
outside-ROI median is retained and plotted as a dynamic-baseline diagnostic,
and the CSV includes ROI median minus outside median. The outside value is not
automatically subtracted because that interpretation still requires validation.
Each box represents the pixel distribution in the mean image for one camera and
exposure: 25th–75th percentiles, median, and 5th–95th percentile whiskers.

The scout fits `raw ROI median = intercept + slope * exposure`; it does not
claim that the intercept is a validated dark correction. Points whose ROI median
exceeds 90% of the 12-bit range or for which any captured frame has more than
0.1% saturated ROI pixels are shown but excluded from fitting. An independently
acquired exposure- and temperature-aware dark library is still required before
producing calibration gains.

Install the optional analysis dependencies into a dedicated calibration
environment, stop the preview producer so it releases the cameras, and write to
a new directory outside Git:

```sh
python -m pip install -e '.[calibration]'
sudo systemctl stop polstation-camera-preview.service
polstation-camera-linearity \
  --config /etc/polstation/config.yaml \
  --output "$HOME/polstation-calibration/linearity-YYYYMMDD-HHMMSS" \
  --exposures-ms 1 2 5 10 15 25 40 60 100 \
  --frames 5 \
  --source-note 'Verified unpolarized five-diffuser source; record control-polarizer relative angle here'
sudo systemctl start polstation-camera-preview.service
```

An output directory without `manifest.json` is an incomplete capture and must be
retained and investigated rather than treated as calibration data. Raw `.raw`
files are little-endian Mono12 samples stored in 16-bit words at the dimensions
recorded per frame. Large calibration captures remain outside Git.

## Earlier Ubuntu workflow

See [the legacy calibration review](legacy-calibration-review.md) for the
reviewed dark/response correction equations, Stokes calculations, false-colour
conventions, and issues to resolve before integrating hardware or methods.
This is a static review, not a validated port.
