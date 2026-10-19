# Architecture

The acquisition process owns future hardware adapters and scientific data writes.
It runs headless, independently of the dashboard, and publishes an atomic health
snapshot. The dashboard binds only to loopback and reads that snapshot.

| Package | Responsibility |
| --- | --- |
| acquisition | Lifecycle, UTC scheduling, parallel raw capture, bounded retries |
| cameras | Camera contracts, demo source, and bounded Vimba diagnostic previews |
| sensors | Timestamped contracts and bounded read-only BME280/EPEVER diagnostic producer |
| calibration | Reserved for calibration loading and validation |
| polarization | Pure diagnostic Stokes/DoLP/AoP preview processing and fixed colour scales |
| logging | Structured stdout logging for journald |
| storage | Paths, free-space checks, atomic JSON publication |
| health | Provenance-bearing scaffold heartbeat and stale detection |
| web | Read-only HTTP dashboard and status endpoint |

Unexpected exceptions terminate acquisition so systemd can restart it. Storage
errors retry with capped exponential delay, and waits can be interrupted by
SIGTERM. Invalid configuration fails startup. No data deletion or simulated
observations occur. The health file can become stale when status writes fail.

Still required for field operation: measured exposure synchronization,
scientifically validated day/night exposure control, hung-driver isolation,
watchdog integration,
power-loss testing, storage endurance and capacity planning, backup monitoring,
and long-duration soak testing. Restarting a crashed process does not detect all
hangs; no systemd watchdog or hardware watchdog is claimed by this scaffold.

## Service port and dashboard roadmap

Administration uses SSH from a laptop connected through the external panel RJ45
and TSW101 network. The dashboard listens on Pi loopback port 8000; SSH forwards
laptop port 8080 to it. Acquisition must remain autonomous when the laptop,
browser, dashboard process or tunnel disconnects.

Dashboard views now include three diagnostic camera previews, exposure/gain
readbacks, BME280 temperature/pressure/humidity, selected EPEVER
PV/battery/load/status telemetry, recorder state, and elapsed time since the last
completed acquisition. Future views include disk capacity and richer
camera/network warnings. Hardware controls are not implemented by the dashboard.
Previews must be derived separately without modifying preserved raw images.
Any future control API belongs behind the acquisition/controller boundary;
the dashboard must never open camera or sensor devices directly. Today the
process boundary consists of atomic read-only health and diagnostic-preview
files exposed by the dashboard's HTTP API; a controller command API is
deliberately deferred.

## Local preview demo

`polstation-dashboard --demo` selects `DemoPreviewSource` behind the read-only
`PreviewSource` snapshot contract. The browser polls `/api/previews` at roughly
one Hz and shows inline SVG images, timestamps and fault states. Static assets
are bundled with the Python package. No third-party browser assets are loaded.
Demo source generation is request-driven, not an acquisition loop, and performs
no scientific storage writes. The normal scaffold dashboard and acquisition
health remain unchanged.

## Real-camera diagnostic preview

`polstation-camera-preview` is a separate, explicitly preview-only producer. It
owns VmbPy and the cameras, issues one barrier-released software-parallel Mono8
capture request per camera, reduces returned frames to bounded PNGs, derives
bounded DoLP/AoP diagnostic maps when local camera-angle mapping is complete,
and atomically replaces `camera-previews.json` in the state root.
It does not write observations. `polstation-dashboard --hardware-preview` reads
that file through `FilePreviewSource`; the web process never imports VmbPy or
opens a device. Old snapshots are marked stale using the configured dashboard
threshold. This first implementation is for hardware evaluation, not the future
scientific acquisition service or synchronized streaming. Request timestamps
and their span are diagnostic only: software-parallel calls do not establish or
measure exposure synchronization.

An optional per-camera `StreamBytesPerSecond` setting bounds aggregate GigE
traffic during software-parallel capture. It is deployment configuration because
the safe value depends on the complete network path. The producer reads and
restores each camera's preceding limit on clean shutdown and publishes the
configured value with its latest-frame snapshot. Transport success does not
upgrade the synchronization claim.

When all three configured cameras have positive `preview_relative_gain` values,
the producer applies those scalars to the corresponding 0°/45°/90° preview
intensities immediately before Stokes processing. Configuration validation also
requires a calibration ID. Snapshot metadata and the dashboard distinguish this
limited relative-sensitivity normalization from missing dark/flat correction,
registration, synchronization, and full scientific calibration.

The diagnostic producer uses bounded shared auto-exposure by default. It measures
the configured high percentile in each bounded Mono8 preview, takes the brightest
of the three, and applies one identical next exposure to all cameras. Camera-local
auto-exposure remains off because independently selected exposures would corrupt
the three-analyser intensity ratios. The controller has explicit exposure limits,
a target, tolerance and maximum per-cycle step in configuration. Its applied and
next exposure, measured brightness and limits are published in the replaceable
snapshot. This protects the diagnostic display from gross day/night exposure
changes; it is not the validated exposure policy for scientific observations.

Polarization processing remains in the producer, not the HTTP request handler.
Only derived PNGs and explicit validity flags cross the atomic snapshot boundary.
No raw image is altered or stored by this preview path.

## Timed scientific observation recorder

`polstation-observation-recorder` is a headless camera owner that schedules the
next UTC wall-clock-aligned slot at the configured interval (600 seconds by
default). It skips missed slots rather than creating a catch-up backlog. At a
slot it requests all three Mono12 frames in software parallel, with one shared
exposure, zero camera gain, gamma 1, camera auto-exposure disabled, and a
commissioned per-camera GigE bandwidth limit. The configured exposure ceiling is
120 seconds. Request times and spans are recorded, but this remains
`software-parallel-unverified`, not validated simultaneous exposure.

Each observation has a bounded number of attempts. Every returned raw buffer is
persisted without pixel changes; `manifest.json` appears only after one attempt
contains three complete Mono12 frames. Failed attempts and low-disk skips remain
explicit, and the recorder never deletes existing data. The latest operational
state is atomically replaced in `observation-recorder.json`; it is not an
observation.

The recorder conflicts with `polstation-camera-preview.service` because Vimba
camera ownership is exclusive. The sensor producer and loopback dashboard may
continue running, and the dashboard reports that the recorder owns the cameras.
Consequently camera preview images can be stale or unavailable during a
recording deployment. Closing the dashboard or SSH tunnel has no effect on the
recorder. Fixed exposure is the safe default. Shared automatic exposure is
implemented and bounded, but is explicitly unvalidated for scientific field use.

## Real-sensor diagnostic preview

`polstation-sensor-preview` runs independently of both camera preview and web
processes. At a bounded interval it opens I2C for one compensated BME280 sample
and issues only documented Modbus function-code 4 input-register reads to the
EPEVER controller. It closes device handles after the sample and atomically
replaces `sensor-preview.json`; it does not write observations or controller
settings. A failure in one adapter is represented explicitly and does not hide a
successful sample from the other.

`FilePreviewSource` merges this latest-value file into the existing read-only
dashboard response and calculates sample ages. The browser and HTTP handler never
import the hardware drivers or open either device. Production sampling schedules,
validation, observation storage, retry policy, and integration into scientific
acquisition remain future work.

The diagnostic deployment keeps the camera producer, sensor producer, and
loopback dashboard in three systemd services grouped by
`polstation-preview.target`. Stopping the target propagates a clean stop to each
process; an individual failure is restarted without coupling the other services.
Only the producers may write bounded runtime state, and only the sensor producer
receives the `i2c` and `dialout` supplementary groups.
