# Commissioning record: software-parallel three-camera transport

Date: 2026-10-12. This record applies to the commissioned Raspberry Pi 5,
TSW101 camera network, and three Allied Vision Mako G-223B cameras. It is a
transport test, not validation of exposure synchronization.

## Reason for the test

The first software-parallel preview release issued the three VmbPy `get_frame`
calls through barrier-released worker threads. Their request timestamps spanned
0.903 ms, but all three frames were incomplete. Each camera's existing
`StreamBytesPerSecond` value had previously read back as 115,000,000 bytes/s,
which would permit 345,000,000 bytes/s in aggregate on a single 1 Gb/s link.
The deployment automatically rolled back to the preceding sequential release.

## Controlled bandwidth test

The preview service was stopped and all three cameras were opened together. The
test temporarily selected:

- `GevSCPSPacketSize`: 1500 bytes, matching the commissioned host MTU;
- `StreamBytesPerSecond`: 30,000,000 bytes/s on each camera;
- `PixelFormat`: Mono8;
- `TriggerMode`: Off;
- `ExposureAuto`: Off; and
- `ExposureTimeAbs`: 15,000 microseconds.

Thirty barrier-released capture cycles were requested, giving 90 returned
frames. All camera settings were restored afterward and the deployed preview
service was restarted.

## Result

- complete frames: 30/30 for each camera, 90/90 total;
- incomplete frames or exceptions: zero;
- request-span min/median/max: 0.751 / 0.781 / 0.881 ms;
- capture-duration min/median/max: 130.748 / 134.203 / 138.601 ms;
- configured aggregate stream limit: 90,000,000 bytes/s;
- host Ethernet RX errors/drops before and after: zero; and
- host Ethernet TX errors/drops/carrier/collisions before and after: zero.

This establishes 30,000,000 bytes/s per camera as a measured working preview
limit for this network and Mono8 test. It does not establish the optimum limit,
guarantee Mono12 scientific capture, or prove that the three exposure intervals
overlap within any particular tolerance. Software request timestamps are host
timestamps and are not camera exposure timestamps. The preview must remain
labelled `software-parallel-unverified` until exposure timing is independently
measured or a validated common trigger is commissioned.

## Implementation decision

The preview configuration exposes `camera_preview.stream_bytes_per_second`.
When non-null, the producer temporarily applies that value to every camera,
publishes it in snapshot metadata, and restores the preceding camera values on
clean shutdown. The tracked examples retain `null`; the measured 30,000,000
bytes/s value belongs in the ignored deployment configuration.
