# Architecture

The acquisition process owns future hardware adapters and scientific data writes.
It runs headless, independently of the dashboard, and publishes an atomic health
snapshot. The dashboard binds only to loopback and reads that snapshot.

| Package | Responsibility |
| --- | --- |
| acquisition | Lifecycle, cancellation, bounded storage retries; future scheduling |
| cameras | Three camera adapter contracts; no SDK or acquisition implementation |
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

Still required for field operation: verified camera SDK support on the target Pi,
PoE and network provisioning, measured synchronization, actual drivers, exposure
control, scientific validation, hung-driver isolation, watchdog integration,
power-loss testing, storage endurance and capacity planning, backup monitoring,
and long-duration soak testing. Restarting a crashed process does not detect all
hangs; no systemd watchdog or hardware watchdog is claimed by this scaffold.

## Service port and dashboard roadmap

Administration uses SSH from a laptop connected through the external panel RJ45
and TSW101 network. The dashboard listens on Pi loopback port 8000; SSH forwards
laptop port 8080 to it. Acquisition must remain autonomous when the laptop,
browser, dashboard process or tunnel disconnects.

Future dashboard views include three camera previews, exposure/integration time,
gain, acquisition countdown, BME280 temperature/pressure/humidity, EPEVER
PV/battery/load telemetry, disk capacity, camera/network status and warnings.
None of these hardware displays or controls is implemented by this scaffold.
Previews must be derived separately without modifying preserved raw images.
Any future control API belongs behind the acquisition/controller boundary;
the dashboard must never open camera or sensor devices directly. Today the
process boundary is an atomic read-only health file exposed by the dashboard's
HTTP API; a controller command API is deliberately deferred.

## Local preview demo

`polstation-dashboard --demo` selects `DemoPreviewSource` behind the read-only
`PreviewSource` snapshot contract. The browser polls `/api/previews` at roughly
one Hz and shows inline SVG images, timestamps and fault states. Static assets
are bundled with the Python package. No third-party browser assets are loaded.
Demo source generation is request-driven, not an acquisition loop, and performs
no scientific storage writes. The normal scaffold dashboard and acquisition
health remain unchanged. A later real preview source should read bounded latest-
frame snapshots from the independent acquisition worker without owning devices
inside the web process.
