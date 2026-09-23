# Review of the earlier three-camera calibration program

Reviewed 2026-09-23. This is a static analysis of the user-supplied Ubuntu
program, not a hardware test or a validated scientific port. The source was
parsed as Python syntax but was not imported or executed. No application code
or calibration assets were copied into polstation.

Source: `mako_3cam_calibration_v5_6_python`, supplied as a text attachment;
5,969 logical lines. SHA-256:
`cfad14c02cea25f5c41b9dfb821ee7bfc2fedf510dd14222e9140cd1b451eba4`.
Line references below refer to that exact source, not polstation files. The
window title still says v5.3, so use this checksum rather than the title to
identify the reviewed version.

## What is reusable

The main value is the documented experimental sequence and diagnostic checks,
not the Tkinter layout. There are separable camera, calibration, numerical,
and rendering functions even though orchestration lives in one GUI class.

1. Discover three Mako cameras, sort by serial, and maintain serial-keyed maps.
2. Select a circular image ROI.
3. Cover all cameras and acquire a multi-exposure dark library.
4. Illuminate the final optical configuration with a stable, spatially uniform,
   unpolarized field; sweep exposures and measure pixel response.
5. Build per-pixel correction gains against a common three-camera reference.
6. Audit the correction arithmetic and validate inter-camera agreement using
   a separate acquisition of an unpolarized field.
7. Acquire analyser images, compare uncorrected and corrected Stokes products,
   and export numeric arrays, masks, diagnostics, false-colour images and legends.

## Camera connection and acquisition

Source: `configure_camera` (77), `capture_stack` (97), constructor (1019),
`verify_camera_mapping` (2527).

The API is **VmbPy / Vimba X**, imported as `vmbpy`, rather than the older
`vimba` Python API. The program enters the Vimba system context, enumerates
cameras, filters by model, sorts by serial and opens each camera using a context
manager. Exactly three matching cameras are required by this GUI.

Explicit settings are Mono12, free-running acquisition (`TriggerMode=Off`),
manual timed exposure, manual gain at 0 dB, packet size 1440 and stream limit
30,000,000 bytes/s. These last two settings document the earlier USB GigE path;
they are not established optimum values for the Pi/TSW101 network. Feature
availability, ranges and actual readback need checking on the target cameras.
The script does not comprehensively reset/read back other potentially relevant
camera processing settings such as black level or gamma.

Frames are acquired synchronously. Timeout scales with exposure, adding roughly
five seconds; settling frames are discarded (three at exposures up to one second,
one above that). Incomplete frames are retried up to five times the requested
frame count. A thrown acquisition exception exits the operation rather than
being covered by that incomplete-frame retry counter. The settling-frame policy
is an empirical assumption to revalidate, not proof of exposure timing.

**All three cameras are acquired sequentially**, often as complete stacks per
camera. Neither hardware triggering nor a common exposure timestamp is used.
Averaging sequential stacks does not provide synchronized sky observations.
Changing clouds or illumination could therefore resemble polarization.

Use explicit configured serial-to-channel-to-analyser-angle mappings in the
instrument. Sorting serials stabilizes discovery order but does not independently
establish the physical analyser orientation.

Current Allied Vision documentation supports the same context-manager and
synchronous/asynchronous acquisition patterns, warns that discovery order is
not deterministic, and notes that feature names depend on camera/firmware.
See the [VmbPy manual](https://docs.alliedvision.com/pythonAPIManual.html).
An [ARM64 release](https://docs.alliedvision.com/ARM.html) exists, but this review
does not establish compatibility or performance for our exact Pi OS/SDK/camera
combination. Record and test that combination before deployment.

## Dark correction

Source: `calculate_dark_products` (212), `interpolate_dark_map` (231),
`capture_dark_library` (2983).

For each serial and exposure, the program calculates a mean dark image and
sample temporal standard deviation (`ddof=1`) across repeated frames. Defaults
are 50 frames at 1, 2, 5, 10, 20, 50, 100, 200 and 500 ms. These are defaults,
not evidence of the exposures actually used in the earlier experiment.

For an intermediate exposure t, every pixel uses:

```text
D(t) = D(t0) + (t - t0) / (t1 - t0) * [D(t1) - D(t0)]
```

Outside the library range the same helper **extrapolates** using the first or
last two maps; it does not clamp to the nearest exposure. With one map it returns
that map unchanged. Audit, validation and DoP workflows warn before extrapolation;
the flat capture path does not provide the same range guard.

This captures per-pixel offsets plus exposure-dependent dark signal, but there
is no temperature axis or sensor-temperature measurement. Night-time exposures
of seconds or longer would extend far beyond the default 500 ms library.
Field calibration needs a defined exposure/temperature validity policy.

## Response fit and cross-camera normalization

Source: `fit_response_slope` (302), `robust_reference_response` (560),
`capture_flat_calibration` (3345), `apply_calibration` (4008).

The illuminated stack is averaged, the matching dark map is subtracted, and
negative corrected values are clipped to zero. Exposures are accepted only if
all cameras have ROI mean corrected signal at least 20 DN and no more than
0.1% of ROI pixels in the averaged raw image at or above 4000 DN. At least two
exposures must remain.

For each pixel p of camera c, a least-squares straight line is fitted through
the origin:

```text
Y(c,p,t) = max(mean_flat(c,p,t) - D(c,p,t), 0)
R(c,p) = sum(t * Y(c,p,t)) / sum(t²)            # DN / ms
```

A fit RMSE map is also calculated and saved. Each camera contributes its median
positive finite response within the ROI; the median of those three medians is
the common reference Rref. Thus each camera has equal weight in choosing the
reference. Valid pixels have response between 0.25 and 4 times that camera's
positive ROI median and lie inside the ROI.

```text
G(c,p) = Rref / R(c,p)                         # dimensionless
Icorrected(c,p,t) = max(Iraw(c,p,t) - D(c,p,t), 0) * G(c,p)
```

Invalid corrected pixels become NaN. This is a relative flat-field and
cross-camera responsivity correction. **It assumes a linear exposure response;
it is not a nonlinear response inversion or LUT-based linearisation.** The
absolute radiometric scale is arbitrary. The DoP workflow uses the same exposure
and fixed gain for all cameras; unequal future exposures need a separately
validated normalization model.

The stable unpolarized flat is essential: unequal polarized input could otherwise
be absorbed into the gain calibration. RMSE is saved but is not used to reject
nonlinear or poor-fit pixels. The exposure acceptance test is based on ROI-wide
statistics, not a per-pixel unsaturated fit selection.

## Polarization mathematics

Source: `calculate_stokes_dop` (634), angle mapping (720), direct check (747),
AoP (825), circular mean (843), test workflow (4885).

The model is:

```text
I(theta) = 0.5 * [S0 + S1 cos(2 theta) + S2 sin(2 theta)]
[S0, S1, S2] = pseudoinverse(A) @ [I1, I2, I3]
DoLP = sqrt(S1² + S2²) / S0
AoP = (0.5 * atan2(S2, S1), converted to degrees) modulo 180°
```

The code labels this DoP, but it measures **degree of linear polarization
(DoLP)**. It does not measure circular Stokes S3, so cannot generally recover
total degree of polarization. The default analyser angles are 0°, 45°, 90°;
the matrix supports other full-rank triplets.

An independent closed-form check for the default geometry uses:

```text
S0 = I0 + I90
S1 = I0 - I90
S2 = 2 I45 - I0 - I90
```

The call site reorders the images by analyser angle before passing them to the
direct helper. Its docstring incorrectly suggests the helper itself performs
that reordering. The check tests numerical agreement, not physical calibration.

The DoP workflow excludes saturated pixels from both raw and corrected products,
keeps their validity masks separate, and intersects masks for like-for-like
comparisons. It uses S0 > 1 DN for the matrix calculation, while the direct
check uses S0 > 1.5; the helper's standalone default is 10. These thresholds
should become one documented policy rather than incidental call-site values.

Numerical DoLP values above one are retained and counted for diagnosis. This is
useful: clipping them in scientific arrays would conceal measurement problems.
The current rank check does not quantify ill-conditioning; a nearly degenerate
angle triplet can amplify noise despite having full rank.

AoP averaging correctly doubles angles before taking a circular mean and halves
the result. However, AoP validity only checks finite Stokes values and the DoP
mask. At S1=S2=0 an orientation is undefined, but `atan2(0,0)` returns a number.
Weak polarization and near-zero circular mean resultant require explicit
confidence/validity treatment. Dark-noise maps are not propagated into Stokes or
AoP uncertainty in this implementation.

## False colour and legends

Source: DoP rendering (791), AoP rendering (862), legends (916 and 940).

- DoLP uses a fixed 0–1 display range, OpenCV JET colours and a linear bar labelled
  0, 0.5 and 1.0. Only the display is clipped. Invalid pixels are black.
- AoP uses cyclic HSV hue for angles in [0°, 180°), full saturation and brightness,
  with invalid pixels black. The hue conversion uses OpenCV's integer 0–179
  convention, which should be reproduced deliberately if matching old PNGs.
- The AoP ring labels geometric directions at 0°, 45°, ..., 315°. Zero is right
  and positive angle is counterclockwise. Colour repeats every 180°: opposite
  sides have the same colour. The labels do not imply a 360° physical AoP range.
- The image and ring use matching hue formulas. Preserve the 180° periodicity,
  fixed DoLP scale and explicit invalid-pixel treatment in the new dashboard.
  Keep rendering separate from scientific arrays and label any later palette
  change rather than silently changing visual comparisons.

The ring is a display convention, not a measured celestial reference. We still
need the analyser angle reference, image handedness/rotation, and transformation
to the chosen sky coordinate convention. No image registration or lens-distortion
mapping was found; the calculation assumes corresponding array pixels observe
the same scene direction. That must be established for the three optical paths.

## Specific issues to resolve before porting

1. **Calibration ROI is not persisted by `save_manifest` (5792).** Loading reads
   `manifest['roi']` (2810 onward), but saving the calibration manifest omits it.
   A fresh session can therefore rebuild gains using its default/current ROI.
   Separate audit/DoP summaries do save ROI, but are not the loader's source.
2. **Loading can write into the wrong calibration folder.** At 2833 the loader
   requests `rebuild_gain_maps_from_response(save_to_disk=True)` before assigning
   the newly selected folder at 2844. The writer at 1698 uses the existing
   `self.calibration_folder`. On a first load it may write nothing; when switching
   folders it can write new gains into the previously active folder. The future
   loader should be read-only, with explicit versioned migration outputs.
3. **Negative dark-subtracted values are clipped before scientific processing.**
   This is intentional legacy behavior, but introduces a positive bias around
   zero signal. Preserve it in reference comparisons; assess signed floating-point
   subtraction and a noise-based validity policy before changing the method.
4. **Saturation checks use averaged images.** Individually saturated frames can
   be hidden by averaging with unsaturated frames. Future quality flags should
   retain per-frame saturation before averaging.
5. **Calibration history is incomplete.** The loader substitutes all exposure
   indices after reload, rather than retaining the originally accepted subset.
   Flat source stacks are not saved; DoP files called `raw` are frame averages,
   not the complete individual exposures. Preserve original frames and accepted
   fit-point identities for reproducibility in polstation.
6. **Metadata is not yet deployment provenance.** There are no asset checksums,
   source Git commit, complete SDK/settings readback or timezone-aware capture
   timestamps. The JSON cross-check key `standard_0_60_120_angles` at 5744 refers
   to a check that actually tests 0°/45°/90°. Treat that as a stale label.
7. **Memory and GUI lifecycle need redesign for the Pi.** A 50-frame float32 stack
   at the assumed 2048×1088 shape is about 425 MiB. Keeping the list of frames
   while stacking can temporarily double that allocation, before other maps and
   intermediates. Streaming mean/variance accumulation can reduce RAM while raw
   frames are stored separately. GUI callbacks/dialogues are unsuitable for a
   headless unattended acquisition controller.

## Suggested integration sequence

1. Obtain one known calibration folder plus a small known input/output example,
   the actual analyser-to-serial mapping and the original SDK/OS versions.
2. Specify and test pure calibration/polarization functions with synthetic
   reference cases before using hardware: dark interpolation, gain correction,
   unpolarized and known linear states, angle permutations, wraparound, invalid
   and saturated pixels, and agreement between both Stokes formulations.
3. Preserve legacy numerical behavior as an explicitly identified baseline.
   Evaluate changes such as signed subtraction, uncertainty masking and nonlinear
   correction separately, with recorded justification and comparison outputs.
4. On the Pi, verify camera discovery and one untouched Mono12 frame, then actual
   settings/timestamps and finally multi-camera acquisition timing.
5. Add versioned, read-only calibration loading and provenance to `calibration/`,
   pure Stokes/DoLP/AoP calculations to `polarization/`, and separate false-colour
   preview rendering to the dashboard pipeline. Keep the current dashboard design.

Open experimental questions: What light source and diffuser were used? How was
unpolarized, spatially uniform illumination verified? Were the final lenses and
analysers present? What were the camera temperatures, accepted exposure range,
physical alignment and measured analyser angles? Which saved results constitute
an independently successful validation? These are commissioning inputs, not
facts that can be recovered from source code alone.
