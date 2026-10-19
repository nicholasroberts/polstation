# Operations

For the normal laptop connection and dashboard procedure, use the
[lab quickstart](quickstart.md). The commands below are service diagnostics and
recovery operations on the Pi.

```sh
sudo systemctl status polstation-preview.target
sudo systemctl status polstation-camera-preview polstation-sensor-preview polstation-dashboard
sudo journalctl -u polstation-camera-preview -n 100 --no-pager
sudo journalctl -u polstation-sensor-preview -n 100 --no-pager
sudo journalctl -u polstation-acquisition -n 100 --no-pager
sudo journalctl -u polstation-dashboard -n 100 --no-pager
sudo systemctl status polstation-observation-recorder
sudo journalctl -u polstation-observation-recorder -n 100 --no-pager
```

`polstation-preview.target` starts and stops the three diagnostic processes as a
group. They remain separate services: a crashed process restarts after 10 seconds
without taking down the other two. The camera and sensor producers publish bounded
latest-value files under `/var/lib/polstation/state`; the dashboard only reads
them. Stop the entire diagnostic stack cleanly with:

```sh
sudo systemctl stop polstation-preview.target
```

## Timed observation recording

The recorder is deliberately not part of `polstation-preview.target` and is not
enabled by the deployment instructions until real-camera commissioning is
complete. Before its first start, set the measured safe
`observation_capture.stream_bytes_per_second` value in the deployed configuration
and validate it:

```sh
sudo -u polstation /opt/polstation/current/.venv/bin/polstation-check-config \
  --config /etc/polstation/config.yaml
sudo systemctl start polstation-observation-recorder.service
```

Starting the recorder stops the conflicting camera-preview service; the sensor
producer and dashboard remain independent. Check its bounded state without
opening camera hardware:

```sh
sudo -u polstation /opt/polstation/current/.venv/bin/python - <<'PY'
import json
from pathlib import Path
state = json.loads(Path('/var/lib/polstation/state/observation-recorder.json').read_text())
for key in ('state', 'updated_at_utc', 'last_acquisition_at_utc',
            'next_acquisition_at_utc', 'last_attempt_state', 'last_error'):
    print(f'{key}: {state.get(key)}')
PY
```

To return to diagnostic camera previews:

```sh
sudo systemctl stop polstation-observation-recorder.service
sudo systemctl start polstation-camera-preview.service
```

Do not run the recorder and ad-hoc Vimba scripts simultaneously. A completed
bundle has `manifest.json`; a directory with `failure.json` is a retained failed
observation and must not be silently treated as complete. The dashboard’s “time
since acquisition” is calculated from the recorder’s last completed manifest,
not from a preview frame.

Acquisition publishes health every 10 seconds by default. The dashboard reports
it stale after 90 seconds. Low disk space reports `low_disk`; existing data is
preserved. Storage write errors retry from 1 to at most 60 seconds. A process
exit triggers systemd restart after 10 seconds, with no restart-rate cutoff;
permanent configuration or permission errors therefore require operator
intervention and will remain visible in the journal.

Journald controls log retention: configure bounded journal storage on the Pi.
A service restart is not a hung-process watchdog. There is no external alerting,
backup automation, driver recovery or autonomous software updater yet.

Before deployment, size storage from measured bytes per three-camera observation
× cadence × deployment duration, plus metadata, derived products and headroom.
Test disk-full behavior, corrupted status, disconnected hardware, power loss,
clock changes, restarts and restore from backup. Protect raw data and calibration
assets with a separately verified backup process. Do not enable retention-based
raw-data deletion without an explicit scientific policy.
