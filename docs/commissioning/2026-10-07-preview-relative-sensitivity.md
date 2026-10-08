# Provisional preview relative-sensitivity normalization

Date: 2026-10-07

This commissioning result records the three scalar multipliers selected from
the controlled exposure and paired-dark scouting work. Camera 2 is the relative
reference:

| Camera ID | Analyser | Preview relative gain |
| --- | ---: | ---: |
| `DEV_000F315B9FC1` | 0° | 1.5087850168 |
| `DEV_000F315B9FC2` | 45° | 1.0000000000 |
| `DEV_000F315B9FC3` | 90° | 0.9841374490 |

Use calibration ID `preview-relative-response-20261007-v1` when these values are
enabled. Relevant external capture directories are
`intensity-60deg-20261007T141414Z`, `intensity-75deg-20261007T143216Z`, and
`dark-extended-20261007T143851Z`. The large raw frames remain outside Git.

These are provisional scalar sensitivity factors for the diagnostic preview,
not final per-pixel radiometric calibration assets. They do not correct the
exposure-dependent dark signal, flat field, lens transmission across the image,
registration, or exposure timing. The dashboard must continue to identify those
limitations and must not label its DoLP/AoP maps fully calibrated.
