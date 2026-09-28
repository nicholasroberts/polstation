# Commissioning record: Pi 5, Vimba X, and three-camera preview

Date: 2026-09-28 (Europe/London)  
Operator account: `admin`  
Host: `polstation`  
Status: successful compatibility and diagnostic-preview test; not field commissioning

This record captures the first end-to-end test of the Raspberry Pi 5, TSW101,
three Allied Vision Mako G-223B cameras, Vimba X, VmbPy, and the polstation
dashboard. Full camera identifiers and serial numbers are intentionally omitted
from Git. The private equipment register must retain the mapping between the
three physical cameras, their full serials, and their eventual analyser angles.

## Scope and non-claims

The work proved camera discovery, individual complete frames, sequential capture
with all cameras connected, and live browser previews. It did not validate raw
scientific acquisition, Mono12, simultaneous exposure, trigger timing, camera
timestamp units, calibration, polarization processing, sustained throughput,
data storage, sensors, or unattended service operation. Dashboard frames were
diagnostic previews and were not written as observations.

## Host baseline

- Raspberry Pi 5, 64-bit ARM (`aarch64`; Debian architecture `arm64`)
- Debian GNU/Linux 13 (trixie)
- Kernel `6.18.50+rpt-rpi-2712`
- glibc 2.41
- Python 3.13.5
- Time zone Europe/London; NTP reported synchronized
- Root filesystem 115 GB, approximately 2 GB used at initial inspection
- No failed systemd units after the OS update and reboot
- Gigabit Ethernet negotiated at 1000 Mb/s, full duplex, with no observed link
  errors or drops during initial inspection

The OS packages were updated. A newer Raspberry Pi EEPROM image was reported as
available, but the offered EEPROM update was declined and was not installed.

## Physical and network topology

The successful bench topology was:

```text
Mac USB Ethernet ── TSW101 port 5 (non-PoE uplink)
Raspberry Pi eth0 ─ TSW101 port 4
Mako cameras ────── TSW101 ports 1–3 (PoE)
Raspberry Pi power ─ USB-C supply
```

The Mac's Internet Sharing supplied the Pi address `192.168.2.2/24` for SSH,
with the Mac at `192.168.2.1`. The cameras sent DHCP discovery but fell back to
distinct IPv4 link-local addresses in `169.254.0.0/16`. The Pi therefore also
uses `169.254.68.1/16` on `eth0`. No DHCP server was installed on the Pi and no
persistent camera addresses were assigned.

Vimba discovery on this tested host selected the last IPv4 address listed for
`eth0`. When NetworkManager installed the link-local address before DHCP, Vimba
sent discovery from `192.168.2.2` and ignored the link-local camera replies even
though packet capture showed all three responses. The working boot sequence is:

1. Keep `Wired connection 1` at `ipv4.method auto`, without the secondary
   address in the connection profile.
2. Add `169.254.68.1/16` after the connection reaches `up` using
   `/etc/NetworkManager/dispatcher.d/90-polstation-camera-address`:

```sh
#!/bin/sh

if [ "$1" = "eth0" ] && [ "$2" = "up" ]; then
    /usr/sbin/ip address add 169.254.68.1/16 dev eth0 2>/dev/null || true
fi
```

The hook is mode 0755. After reboot, `ip -brief address show eth0` listed the
DHCP address first and camera-side address second, and Vimba found all three
cameras. This is a commissioning workaround, not the final field address plan.

## Vimba X installation

- Archive: `VimbaX_Setup-2026-2-Linux_ARM64.tar.gz`
- SHA-256:
  `bc223962fc393878c71a6efce8215ce231cc3089bb1a85fffc6fb6eeee43c091`
- Installation root: `/opt/alliedvision/VimbaX_2026-2`
- Native VmbC version reported by the examples: 1.3.1
- VmbPy wheel version: 1.2.2
- VmbPy environment: `/home/admin/venvs/vmbpy-2026-2`

The archive's ownership was normalized to `root:root`. The bundled transport
installer was inspected but not executed because it also creates a USB udev rule
with world-writable mode 0666. Only GigE was required. A GigE-only transport
directory was created at `/opt/alliedvision/VimbaX_2026-2/cti-gige`, containing
links to `VimbaGigETL.cti` and `VimbaGigETL.xml`. The persistent profile sets:

```sh
export GENICAM_GENTL64_PATH="/opt/alliedvision/VimbaX_2026-2/cti-gige${GENICAM_GENTL64_PATH:+:$GENICAM_GENTL64_PATH}"
```

The GigE transport was confirmed as an AArch64 ELF object and all dependencies
reported by `ldd` resolved. Restricting the GenTL path removed the bundled camera
simulator from discovery, leaving one GigE transport layer and one interface.

Allied Vision publishes an ARM64 archive and lists Mako as compatible, but its
ARM release notes do not list Raspberry Pi OS as a tested platform. These results
are project compatibility evidence, not a vendor-support claim.

## Camera results

Each physical camera was connected alone and identified privately. Each had an
initial `GevSCPSPacketSize` of 8228 while Pi `eth0` used MTU 1500. Untouched
captures were incomplete. A controlled test temporarily set packet size 1500,
captured one frame, and restored 8228 in a `finally` block.

All three cameras independently returned:

- `FrameStatus.Complete`
- 2048 × 1088 pixels
- Mono8
- 2,228,224-byte image buffer
- original packet size restored to 8228 after the test

With all cameras connected, the native VmbC example discovered exactly three
distinct Mako G-223B devices. A sequential VmbPy test opened all three and
obtained one complete frame from each at packet size 1500, restoring the original
packet settings afterward. Concurrent full-rate streaming was not tested.

## Real-preview dashboard test

The diagnostic producer `polstation-camera-preview` was added. It runs separately
from the dashboard and:

- requires exactly three discovered cameras;
- opens all three through VmbPy;
- temporarily selects packet size 1500, Mono8, and trigger mode Off;
- captures sequentially at approximately one cycle per second;
- down-samples each frame to a bounded grayscale PNG no larger than 640 × 400;
- atomically replaces one `camera-previews.json` latest-state file;
- keeps no growing frame queue and writes no observations; and
- restores packet size, pixel format, and trigger mode on clean shutdown.

The dashboard uses `--hardware-preview` to read that file and never imports or
opens Vimba. It labels the feed as real, preview-only, sequential, and
unsynchronized. The browser reached the loopback dashboard through:

```sh
ssh -L 8080:127.0.0.1:8000 admin@192.168.2.2
```

The Mac browser used `http://127.0.0.1:8080`; port 8000 remained bound only to
Pi loopback. Three changing real-camera panels were visually observed. Covering
each lens in turn is the required physical mapping check before assigning camera
roles or analyser angles.

## Verification performed

- Hardware-independent suite on the Mac: 13 tests passed.
- Configuration validation passed.
- Updated demo dashboard rendered correctly in a browser.
- Pi smoke-test snapshot reported `hardware_ready: true`, three live cameras,
  advancing software frame numbers, Mono8, and non-empty preview payloads.
- The real dashboard returned HTTP 200 for its page, assets, and preview endpoint
  while all three panels updated through the SSH tunnel.

## Follow-up gates

Before scientific or unattended operation:

- assign and record physical camera roles without committing full serials;
- choose and validate the permanent service/camera address plan;
- select and verify the required raw pixel format and bit depth;
- measure three-camera bandwidth, packet loss, and recovery behavior;
- configure and validate exposure triggering and synchronization;
- record camera timestamp units and relate them to the host time source;
- preserve raw frames and complete provenance separately from previews;
- add camera-preview/acquisition systemd deployment only after failure and
  restart behavior are tested; and
- complete sensor, calibration, storage, power-loss, and soak testing.
