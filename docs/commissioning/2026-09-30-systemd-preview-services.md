# Commissioning record: persistent diagnostic preview services

Date: 2026-09-30  
Platform: Raspberry Pi 5, Debian 13 (arm64), systemd 257  
Software commit: `d59c4a88debc0f1785ba7fceec862ce7591b7d5e`  
Status: automatic startup, independent restart, grouped shutdown, and reboot recovery verified

This session converted the previously verified manual camera, sensor, and
dashboard commands into three independent systemd services. It did not enable
scientific acquisition or observation recording.

## Installed layout

- Dedicated non-login account: `polstation`
- Immutable release: `/opt/polstation/releases/d59c4a8`
- Active release symlink: `/opt/polstation/current`
- Root-owned configuration: `/etc/polstation/config.yaml`, mode `0640`, group `polstation`
- Root-owned Vimba X environment: `/etc/polstation/vimbax.env`, mode `0640`
- Replaceable runtime state: `/var/lib/polstation/state`, owned by `polstation`
- Reserved scientific data root: `/var/lib/polstation/data`, not written by previews

The release has its own Python virtual environment. It contains VmbPy 1.2.2,
MinimalModbus 2.1.1, RPi.bme280 0.2.4, and the application with the optional
sensor dependencies. `pip check` reported no broken requirements. The protected
configuration retained the commissioned three-camera 0°/45°/90° mapping,
BME280 bus 1/address `0x76`, and the stable EPEVER serial-by-id settings.

## Service boundary

`polstation-preview.target` groups:

- `polstation-camera-preview.service` — owns VmbPy and the GigE cameras;
- `polstation-sensor-preview.service` — owns BME280 I2C and read-only EPEVER Modbus; and
- `polstation-dashboard.service` — reads snapshots and listens only on `127.0.0.1:8000`.

All run as `polstation`. Only the sensor service receives supplementary `i2c`
and `dialout` groups. Only the camera service reads the Vimba X GenTL environment.
The two producers may write `/var/lib/polstation/state`; the dashboard has
read-only access and no hardware-device view. All units use restart-on-exit
behavior with a 10-second delay and an unlimited start interval.

`systemd-analyze verify` accepted all rendered units before installation. Each
service was initially installed disabled and tested separately.

## Hardware results under the service account

The sensor service published both BME280 and EPEVER states as `live`. Its process
had effective group IDs for `dialout` and `i2c`, confirming device permissions
without running the application as `admin` or root.

The camera service found all three Mako G-223B cameras and published three live
Mono8 previews plus live sensor-relative AoP/DoLP products. Vimba X logged its
expected jumbo-packet performance recommendation; the producer retained the
commissioned 1500-byte diagnostic packet setting required by the current MTU.

The dashboard listened only on Pi loopback and its API reported three live
cameras, both sensors live, and live polarization. The browser dashboard was
also inspected successfully through the SSH tunnel on laptop port 8080.

## Lifecycle and recovery tests

Starting `polstation-preview.target` brought all three services active. Stopping
the target made the target and all three services inactive, with no preview
processes left behind. Starting the target again restored all hardware and
derived states to live.

The sensor producer was then deliberately killed with `SIGKILL`. Systemd recorded
the signal failure, waited 10 seconds, assigned a new PID, and restored both
sensor states to live. The camera and dashboard services stayed active throughout.

Finally, the target was enabled and the Pi rebooted. Approximately one minute
after boot:

- the target and all three services were active;
- `systemctl --failed` reported zero failed units;
- all three camera states were live;
- BME280 and EPEVER states were live; and
- the polarization state was live.

This establishes automatic unattended startup for the diagnostic stack. It does
not establish synchronized exposure, calibrated products, scientific recording,
or year-long reliability.

## Remaining work

- Run a longer soak test and watch memory, CPU, temperatures, logs, and frame ages.
- Test physical camera, I2C, and USB-RS485 disconnect/reconnect behavior.
- Bound and verify persistent journald storage.
- Test power interruption and recovery rather than only an orderly reboot.
- Define alerting and watchdog policy without hiding persistent hardware faults.
- Create a reviewed release tag and freeze/archive the deployed dependency set.
