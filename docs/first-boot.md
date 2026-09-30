# First SSH and Vimba X camera bring-up on Raspberry Pi 5

This procedure stops after proving that a freshly flashed Raspberry Pi OS Lite
host can be reached by SSH, load Allied Vision's GigE transport layer, discover
each Mako G-223B, and acquire one unchanged test frame. It does **not** deploy the
polstation application, create services, set permanent camera addresses, update
camera firmware, tune bandwidth, or establish synchronized acquisition.

Use a local Pi console until a second SSH session has been proven. Record command
output, OS image/date, Pi serial, Vimba X archive name and hash, SDK/API versions,
camera serials, firmware versions when readable, interface/MAC mapping, and test
results in the private commissioning record. Do not commit credentials or full
device serials to Git.

## Compatibility gate

Allied Vision currently publishes a Linux ARM64 Vimba X archive, documents an
ARMv8 64-bit CPU and Gigabit Ethernet as the ARM GigE requirements, and lists
Mako as compatible with Vimba X. However, its current ARM64 release notes list
Jetson/Ubuntu as the tested ARM platform, not Raspberry Pi 5 or Raspberry Pi OS.
Treat the steps below as a compatibility test, not proof of vendor support or
field readiness.

Authoritative references:

- [Vimba X ARM64 release notes](https://docs.alliedvision.com/ARM.html)
- [Linux and ARM installation](https://docs.alliedvision.com/installation.html)
- [Vimba X compatibility](https://docs.alliedvision.com/compatibility.html)
- [VmbPy manual](https://docs.alliedvision.com/pythonAPIManual.html)
- [Vimba X examples](https://docs.alliedvision.com/examplesOverview.html)
- [Mako G camera user guide](https://www.alliedvision.com/assets/support/Camera-Documentation/Allied-Vision/User-guides/Mako_TechMan_en.pdf)

Do not continue with an x86-64 archive or a 32-bit OS.

## 1. Prove the first SSH connection

At the Pi's local console, obtain the actual username, addresses, and SSH host-key
fingerprint:

```sh
whoami
hostnamectl
ip -brief address
sudo systemctl enable --now ssh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

From the laptop, substitute the observed username and address. Compare the
displayed ED25519 fingerprint with the console before accepting it:

```sh
ssh -o StrictHostKeyChecking=ask OPERATOR@ACTUAL_PI_ADDRESS
```

If Raspberry Pi Imager did not install the operator's public key, run this from
the laptop and reconnect:

```sh
ssh-copy-id OPERATOR@ACTUAL_PI_ADDRESS
ssh OPERATOR@ACTUAL_PI_ADDRESS
```

Keep the console open. Do not disable password login or change the network during
this experiment. First prove that a second independent SSH session works.

## 2. Capture the baseline and confirm ARM64

Run on the Pi through SSH:

```sh
cat /etc/os-release
uname -a
uname -m
dpkg --print-architecture
getconf GNU_LIBC_VERSION
python3 --version
timedatectl status
systemctl --failed
```

Expected architecture results are `aarch64` from `uname -m` and `arm64` from
`dpkg --print-architecture`. Allied Vision documents glibc 2.27 or later for
Linux. Stop if these gates fail. Record whether the clock is synchronized; a
correct-looking timestamp alone is not proof of synchronization.

Update the new image and install only the bring-up tools:

```sh
sudo apt-get update
apt list --upgradable
sudo apt-get full-upgrade
sudo apt-get install ca-certificates ethtool python3-venv python3-pip tar
sudo reboot
```

Reconnect by SSH and repeat the architecture, time, and failed-unit checks.

## 3. Prove the Ethernet path with one camera

Start with one camera connected to the TSW101, not all three. Confirm the switch's
PoE capability and budget from its own documentation before relying on it to
power a camera. Do not connect the Pi's Ethernet port directly to an unknown PoE
source.

Identify the actual wired interface and inspect it without changing settings:

```sh
ip -brief link
ip -brief address
ip route
nmcli device status
ip -s link
```

Replace the interface token below with the name just observed:

```sh
ethtool ACTUAL_WIRED_INTERFACE
```

Record link speed, duplex, Pi interface MAC, cabling, and switch ports. The Mako
guide says full Gigabit operation requires all four Ethernet pairs. Do not copy
an example subnet, force an address, enable jumbo frames, or alter packet size at
this stage. Vimba X discovery is the next test; it can find GigE cameras before
ordinary IP tools can communicate with them.

## 4. Obtain and inspect the Vimba X ARM64 archive

On the laptop, download the current **Linux ARM64** archive from Allied Vision's
[official Vimba X download page](https://www.alliedvision.com/en/support/software-downloads/vimba-x-sdk/vimba-x).
Record its exact version and SHA-256 hash. Transfer that exact file to the Pi;
the tokens below must be replaced:

```sh
sha256sum ACTUAL_VIMBAX_ARM64_ARCHIVE
scp ACTUAL_VIMBAX_ARM64_ARCHIVE OPERATOR@ACTUAL_PI_ADDRESS:
```

On the Pi, recompute the hash and compare it character-for-character with the
laptop result. Inspect the archive before extracting it as root:

```sh
sha256sum "$HOME/ACTUAL_VIMBAX_ARM64_ARCHIVE"
tar -tf "$HOME/ACTUAL_VIMBAX_ARM64_ARCHIVE"
sudo install -d -o root -g root -m 0755 /opt/alliedvision
```

Stop if the archive is not ARM64, its hash changed in transfer, or the listing
contains unexpected absolute paths or parent-directory traversal. Then extract:

```sh
sudo tar -xf "$HOME/ACTUAL_VIMBAX_ARM64_ARCHIVE" -C /opt/alliedvision
find /opt/alliedvision -type f -name Install_GenTL_Path.sh -print
```

Set `VIMBAX_ROOT` to the single extracted directory containing `cti/` and `bin/`,
normalize the archive's numeric ownership, and inspect the vendor README and
installer before deciding whether to execute it:

```sh
VIMBAX_ROOT='/opt/alliedvision/replace-with-extracted-vimbax-directory'
test -d "$VIMBAX_ROOT/cti"
sudo chown -R root:root "$VIMBAX_ROOT"
find "$VIMBAX_ROOT" -maxdepth 2 -iname 'readme*' -print
less "$VIMBAX_ROOT/cti/Install_GenTL_Path.sh"
```

The 2026-2 installer registers every bundled transport layer and creates a USB
udev rule with mode 0666. That is unnecessary for a GigE-only installation and
was not used during the 2026-09-28 test. Instead, create a directory exposing
only the GigE transport and register that directory in the login environment.
Replace the example version if a different release was downloaded:

```sh
sudo install -d -o root -g root -m 0755 /opt/alliedvision/VimbaX_2026-2/cti-gige
sudo ln -s ../cti/VimbaGigETL.cti /opt/alliedvision/VimbaX_2026-2/cti-gige/VimbaGigETL.cti
sudo ln -s ../cti/VimbaGigETL.xml /opt/alliedvision/VimbaX_2026-2/cti-gige/VimbaGigETL.xml
printf '%s\n' '#!/bin/sh' 'export GENICAM_GENTL64_PATH="/opt/alliedvision/VimbaX_2026-2/cti-gige${GENICAM_GENTL64_PATH:+:$GENICAM_GENTL64_PATH}"' | sudo tee /etc/profile.d/VimbaX_GenTL_Path_64bit.sh >/dev/null
sudo chmod 0644 /etc/profile.d/VimbaX_GenTL_Path_64bit.sh
```

Start a new login shell or reboot before testing. Do not add GUI packages to
Raspberry Pi OS Lite merely to run Vimba X Viewer. If USB cameras are later
required, review and replace the vendor udev permissions deliberately rather
than accepting a world-writable device rule without review.

## 5. Verify the transport layer after reboot

Reconnect and restore `VIMBAX_ROOT` to the actual installed directory:

```sh
VIMBAX_ROOT='/opt/alliedvision/replace-with-extracted-vimbax-directory'
printenv GENICAM_GENTL64_PATH
find "$VIMBAX_ROOT/cti" -type f -name '*.cti' -print
find "$VIMBAX_ROOT/bin" -maxdepth 1 -type f -print
```

The GenTL path must include the SDK transport-layer location. If it does not,
inspect the profile file and the vendor troubleshooting guide; do not improvise
a system-wide library copy.

If the SDK contains a prebuilt `ListCameras` executable, run that vendor example
first. GigE discovery may take several seconds. Record the exact command and
output. If no camera appears, capture diagnostics before changing anything:

```sh
ip -brief address
ip -s link
ip neigh
journalctl -k -b --no-pager
```

Check power, link LEDs, cabling, switch port, and subnet plan. Do not force a
camera IP yet. Vimba X supplies `ConfigIp` and `ForceIp` examples, but using them
requires the approved address plan and a separately recorded change procedure.

If packet capture shows a camera falling back to `169.254.0.0/16`, the Pi needs
an address and route in that prefix. First conflict-check the proposed Pi address
with `arping -D`, then add it temporarily. Use an address selected for this bench,
not the token below:

```sh
sudo arping -D -I ACTUAL_WIRED_INTERFACE -c 3 ACTUAL_UNUSED_PI_LINK_LOCAL
sudo ip address add ACTUAL_UNUSED_PI_LINK_LOCAL/16 dev ACTUAL_WIRED_INTERFACE
```

Do not install a DHCP server merely to solve this discovery test. Record how the
address will persist before rebooting. On a multi-address interface, capture the
Vimba discovery exchange and verify its source address; the 2026-09-28 test found
that address ordering affected which subnet Vimba used.

## 6. Install the SDK-matched VmbPy wheel

Use the wheel supplied in the same SDK archive rather than assuming the PyPI
package includes the required transport layer. Locate it and read its README:

```sh
find "$VIMBAX_ROOT/api/python" -maxdepth 2 -type f -name '*.whl' -print
find "$VIMBAX_ROOT/api/python" -maxdepth 2 -iname 'readme*' -print
python3 -m venv "$HOME/venvs/vmbpy"
```

Set the wheel path to the one actually found, install it in the isolated virtual
environment, and print versions:

```sh
VMBPY_WHEEL='/opt/alliedvision/replace-with-actual-vmbpy-wheel.whl'
"$HOME/venvs/vmbpy/bin/python" -m pip install "$VMBPY_WHEEL"
"$HOME/venvs/vmbpy/bin/python" -c 'import vmbpy; print(vmbpy.__version__)'
```

Stop on an `Invalid VmbC Version` error. Reinstall the wheel from the matching
SDK rather than mixing SDK/API versions. VmbPy 1.2.2 does not expose
`VmbSystem.get_version()`; use the SDK's native `ListCameras_VmbC` example to
print the underlying VmbC version.

## 7. Discover one camera without changing it

Use the vendor's `list_cameras.py` example if present under
`$VIMBAX_ROOT/api/python`. Otherwise this read-only check is sufficient:

```sh
"$HOME/venvs/vmbpy/bin/python" - <<'PY'
from vmbpy import VmbSystem

with VmbSystem.get_instance() as vmb:
    cameras = vmb.get_all_cameras()
    print(f"camera_count={len(cameras)}")
    for camera in cameras:
        print(camera)
PY
```

Expect exactly one camera during this step. Record its identity privately and
confirm physically that it is the intended Mako G-223B. Discovery alone does not
prove streaming, address persistence, or correct analyser mapping.

## 8. Acquire one untouched frame

With only that camera connected, acquire one frame without setting exposure,
gain, ROI, pixel format, trigger mode, packet size, or throughput limits:

```sh
"$HOME/venvs/vmbpy/bin/python" - <<'PY'
from vmbpy import VmbSystem

with VmbSystem.get_instance() as vmb:
    cameras = vmb.get_all_cameras()
    if len(cameras) != 1:
        raise SystemExit(f"expected one camera, found {len(cameras)}")
    with cameras[0] as camera:
        frame = camera.get_frame(timeout_ms=5000)
        print(f"camera={camera}")
        print(f"status={frame.get_status()}")
        print(f"size={frame.get_width()}x{frame.get_height()}")
        print(f"pixel_format={frame.get_pixel_format()}")
        print(f"buffer_bytes={frame.get_buffer_size()}")
        print(f"frame_id={frame.get_id()}")
        print(f"camera_timestamp={frame.get_timestamp()}")
PY
```

This intentionally does not save or convert pixels. A complete frame proves a
basic data path only; the camera timestamp's unit/source and its relation to Pi
UTC remain unverified.

If the frame is incomplete, compare `GevSCPSPacketSize` with the host MTU before
changing either. In the 2026-09-28 test the cameras used 8228-byte packets while
Pi `eth0` remained at MTU 1500. A controlled test at packet size 1500 produced
complete frames. Save the original value, change it only for the test, and
restore it in a `finally` block. Do not claim success from a frame whose status
is not `FrameStatus.Complete`.

Power down or disconnect according to the camera/switch manuals, label the first
result, and repeat the one-camera discovery/frame test for each remaining camera.
Only after all three pass individually should all three be connected for a
read-only discovery count. Do not proceed directly to simultaneous streaming:
bandwidth allocation, packet sizing, loss monitoring, and exposure timing need a
separate measured test.

## Stop conditions

Stop and preserve outputs if any of these occur:

- the Pi is not running 64-bit ARM or does not meet the documented glibc gate;
- the vendor ARM64 transport layer fails to load on Raspberry Pi OS;
- camera power, Gigabit link, identity, firmware, or network ownership is unclear;
- discovery requires an unapproved IP change;
- a frame is incomplete, times out, or differs from the expected native format;
- kernel/network counters show errors or drops;
- the test would require guessed packet sizes, throughput limits, exposure,
  trigger, PTP, firmware, or persistent IP settings.

These outcomes are useful compatibility evidence. They should be resolved before
the repository gains a real camera adapter or any unattended acquisition service.
