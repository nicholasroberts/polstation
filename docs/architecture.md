# Architecture

The acquisition process owns future hardware adapters and scientific data writes.
It runs headless, independently of the dashboard, and publishes an atomic health
snapshot. The dashboard binds only to loopback and reads that snapshot.

| Package | Responsibility |
| --- | --- |
| acquisition | Lifecycle, cancellation, bounded storage retries; future scheduling |
| cameras | Camera contracts, demo source, and bounded Vimba diagnostic previews |
| sensors | Timestamped BME280 and EPEVER sample contracts; no drivers |
| calibration | Reserved for calibration loading and validation |
| polarization | Reserved for processing derived products |
| logging | Structured stdout logging for journald |
| storage | Paths, free-space checks, atomic JSON publication |
| health | Provenance-bearing scaffold heartbeat and stale detection |
| web | Read-only HTTP dashboard and status endpoint |

Unexpected exceptions terminate acquisition so systemd can restart it. Storage
errors retry with capped exponential delay, and waits can be interrupted by
SIGTERM. Invalid configuration fails startup. No data deletion or simulated
observations occur. The health file can become stale when status writes fail.

Still required for field operation: vendor-supported camera SDK operation on the
target Pi, permanent network provisioning, measured synchronization, production
acquisition, exposure control, scientific validation, hung-driver isolation,
watchdog integration,
power-loss testing, storage endurance and capacity planning, backup monitoring,
and long-duration soak testing. Restarting a crashed process does not detect all
hangs; no systemd watchdog or hardware watchdog is claimed by this scaffold.

## Service port and dashboard roadmap

Administration uses SSH from a laptop connected through the external panel RJ45
and TSW101 network. The dashboard listens on Pi loopback port 8000; SSH forwards
laptop port 8080 to it. Acquisition must remain autonomous when the laptop,
browser, dashboard process or tunnel disconnects.

Dashboard views now include three diagnostic camera previews and exposure/gain
readbacks. Future views include acquisition countdown, BME280
temperature/pressure/humidity, EPEVER
PV/battery/load telemetry, disk capacity, camera/network status and warnings.
Sensor displays and hardware controls are not implemented by this scaffold.
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
owns VmbPy and the cameras, captures sequential Mono8 frames, reduces them to
bounded PNGs, and atomically replaces `camera-previews.json` in the state root.
It does not write observations. `polstation-dashboard --hardware-preview` reads
that file through `FilePreviewSource`; the web process never imports VmbPy or
opens a device. Old snapshots are marked stale using the configured dashboard
threshold. This first implementation is for hardware evaluation, not the future
scientific acquisition service or synchronized streaming.
