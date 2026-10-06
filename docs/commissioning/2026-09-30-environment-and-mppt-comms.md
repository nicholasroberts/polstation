# Commissioning record: BME280 and EPEVER communications

Date: 2026-09-30  
Platform: Raspberry Pi 5, Debian 13 (arm64)  
Status: read-only communications, diagnostic dashboard path, and persistent
systemd deployment verified on the Pi; not a scientific observation path

This session established communication with the installed BME280 environmental
sensor and EPEVER Tracer 2210AN MPPT controller. It did not calibrate either
sensor, change controller settings, or integrate readings into scientific
observations. Deployment-specific device paths remain in the ignored local YAML
configuration and are intentionally omitted here.

## BME280 over I2C

I2C was initially disabled. It was enabled with `raspi-config`, `i2c-tools` and
Debian's `python3-bme280` package were installed, and the Pi was rebooted.

- Linux bus: `/dev/i2c-1`
- I2C address: `0x76` (stored as decimal `118` in YAML)
- Bosch chip-ID register `0xD0`: `0x60`, confirming BME280 rather than BMP280
- Operator account: member of the `i2c` group; application access required no root

Five samples at two-second intervals were stable:

| Quantity | Observed range |
| --- | ---: |
| Temperature | 18.15–18.16 °C |
| Pressure | 1003.06–1003.16 hPa |
| Relative humidity | 53.85–53.87 %RH |

These are the sensor's compensated outputs and establish communication only.
They have not been checked against traceable references, corrected for mounting
or enclosure effects, or accepted as field-calibrated measurements.

## EPEVER over USB-RS485/Modbus RTU

The USB adapter enumerated as QinHeng Electronics `1a86:55d3`, produced
`/dev/ttyACM0`, and provided a persistent `/dev/serial/by-id/` link. The exact
identifier is held only in ignored local configuration. The operator account was
already a member of `dialout`.

Read-only Modbus communication was verified with MinimalModbus 2.1.1 and
pyserial 3.5 using:

- RTU mode, 115200 baud, 8 data bits, no parity, 1 stop bit;
- slave address 1; and
- function code 4 (read input registers).

No holding register, coil, or controller setting was written. The register
addresses and scaling came from EPEVER's published B-Series/A-Series Modbus
specification. The first successful request read PV voltage from `0x3100`.

The expanded read-only sample returned:

| Quantity | Observed value |
| --- | ---: |
| PV voltage/current/power | 6.07 V / 0.00 A / 0.00 W |
| Battery voltage / state of charge | 13.01 V / 68% |
| Battery charge current/power | 0.00 A / 0.00 W |
| Load voltage/current/power | 13.01 V / 0.75 A / 9.75 W |
| Battery net current | -0.78 A |
| Controller temperature | 20.25 °C |
| Controller-reported battery temperature | 19.66 °C |

PV voltage was below battery voltage, consistent with no charging. The negative
battery current was consistent with the approximately 9.75 W load. Status words
reported the controller running, battery voltage normal, no charging, load
running, and no controller fault. The remote-battery-temperature register
returned `0.00 °C`; without a validated remote probe this is unavailable data,
not a physical zero-degree measurement.

Energy counters were readable. At this early test they reported 0.01 kWh total
consumed and 0.00 kWh total generated. Counter semantics, rollover, persistence,
and agreement with independent measurements still require validation.

## End-to-end diagnostic dashboard verification

Commit `f797f39` was deployed to the Pi. The optional `sensor-preview`
dependencies installed successfully into the existing VmbPy virtual environment,
and the ignored local configuration passed validation. The independent sensor
producer published a bounded `sensor-preview.json` snapshot every five seconds.
Both links reported `live`; representative sample durations were 27.5 ms for the
BME280 and 179.7 ms for the EPEVER register group.

The camera producer, sensor producer, and loopback-bound dashboard were then run
as three separate processes. The dashboard API reported:

- three camera states `live`;
- BME280 and EPEVER states `live`; and
- polarization preview state `live`.

The browser dashboard was inspected through an SSH tunnel from laptop port 8080
to Pi loopback port 8000. It displayed all three camera previews, diagnostic
DoLP/AoP maps, BME280 temperature/pressure/humidity, and the selected solar,
battery, load, energy, temperature, charging, and controller-status values.
The tunnel was closed independently, after which all three Pi processes were
stopped cleanly with `SIGINT`.

This verified the diagnostic data path and process separation only. The values
were neither recorded as observations nor independently calibrated. Persistent
service commissioning is recorded separately in the systemd preview record.

## Local configuration retained

The ignored Pi-local configuration now records:

- BME280 bus 1 and address `0x76`;
- the stable USB serial by-id path;
- Modbus slave address 1; and
- 115200 baud, parity `N`, one stop bit.

Do not replace the stable serial path with `/dev/ttyACM0` in deployment config;
the kernel number can change after reconnects. Future production code must mark
missing, invalid, or stale values explicitly and must not interpret a missing
temperature sensor as zero.

## Remaining work

- Promote the diagnostic adapters into the future observation acquisition design.
- Record sampling time, read duration, register source, units, and validity.
- Decide polling intervals and retry behavior, then test disconnect/reconnect.
- Validate BME280 readings against suitable references and its installed thermal environment.
- Validate MPPT voltage/current/power and energy counters independently.
- Confirm the optional sensor dependencies install reproducibly on a clean Pi environment.

## References

- [EPEVER Tracer-AN manual](https://www.epever.com/upload/file/2107/Tracer-AN-Manual-EN-V2.3_Software%20SV200.pdf)
- [EPEVER B-Series Modbus specification V2.3](https://s319fedb1146f0442.jimcontent.com/download/version/1673946360/module/8195322761/name/ControllerProtocolV2.3.pdf)
