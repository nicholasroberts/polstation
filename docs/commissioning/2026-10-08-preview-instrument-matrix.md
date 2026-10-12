# Provisional preview instrument matrix

Date: 2026-10-08

Calibration ID: `preview-instrument-matrix-20261008-v1`

The reviewed small metadata asset is
`config/calibrations/preview-instrument-matrix-20261008-v1.yaml`. The deployment
configuration embeds this mapping and records the calibration ID above.

This commissioning calibration is for diagnostic preview maps only. It is not
a scientific observation calibration. The optical order during acquisition was:

```text
fluorescent source -> five depolarizing diffuser layers -> rotatable linear
polarizer -> final fisheye lenses and fixed 0/45/90 degree camera analysers
```

The five diffuser layers remained installed for every polarized position. The
top polarizer was stepped through four nominal 45° rotations. Position A was
physically aligned with the Camera 3 analyser, establishing a +90° offset from
the fitted relative coordinate to sensor-relative AoP.

## Response model

Rows are ordered by the exact camera IDs below. The matrix maps relative Stokes
`[S0, Q, U]` to dark-subtracted Mono8 response rate:

```text
camera_order = [
  DEV_000F315B9FC1,
  DEV_000F315B9FC2,
  DEV_000F315B9FC3,
]

M = [
  [2.9987810, -1.8999429, -2.1693866],
  [4.3496859,  3.6071487, -2.6424753],
  [4.3280390,  3.3462221,  2.6509674],
]

sensor_aop_offset_deg = 90
```

For each exposure, the implementation linearly interpolates the central-ROI
median dark signal from external capture
`dark-extended-20261007T143851Z`, then divides the Mono12 DN by 16 to match the
Mono8 preview scale. The measured exposure range is 15–1500 ms; the matrix
preview is deliberately unavailable outside this interval.

| Exposure (ms) | C1 dark (Mono12 DN) | C2 dark (Mono12 DN) | C3 dark (Mono12 DN) |
| ---: | ---: | ---: | ---: |
| 15 | 20.0 | 25.4 | 12.2 |
| 30 | 21.8 | 27.4 | 13.0 |
| 75 | 27.4 | 37.0 | 21.6 |
| 150 | 37.8 | 52.6 | 37.6 |
| 225 | 48.4 | 70.2 | 52.6 |
| 375 | 70.4 | 102.8 | 82.8 |
| 600 | 103.8 | 151.6 | 130.0 |
| 900 | 148.2 | 220.2 | 193.6 |
| 1500 | 239.2 | 355.8 | 323.6 |

## Validation

The four fitting positions recovered relative AoP values 0.12°, 45.61°, 89.87°,
and 134.40°, with unclipped DoLP 101.56%, 100.14%, 97.36%, and 101.00%.

An independently withheld +22.5° position used a 15.129 ms shared exposure and
raw central-ROI medians 2, 73, and 129 Mono8 DN. The fitted matrix recovered:

- relative AoP 24.02° (expected 22.5°, error +1.52°);
- sensor-relative AoP 114.02° (expected 112.5°);
- unclipped DoLP 102.25%.

This withheld result supports trying the matrix in the diagnostic dashboard. It
does not validate the whole image or wider operating envelope. Outstanding work
includes per-pixel temperature-aware dark maps, flat-field/lens correction,
spatial registration, synchronized capture, additional source angles and
intensities, stable radiometric reference measurements, and repeatability over
temperature and time. Raw calibration captures remain outside Git.

The deployed diagnostic maps are intentionally restricted to the reviewed
central circular fisheye ROI (centre 50%/50%, radius 60% of half the smaller
preview dimension). The region outside that circle is rendered black. This is a
display mask, not a flat-field correction or a claim that every pixel inside the
circle has been calibrated.
