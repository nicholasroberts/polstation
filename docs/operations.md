# Operations

```sh
sudo systemctl status polstation-preview.target
sudo systemctl status polstation-camera-preview polstation-sensor-preview polstation-dashboard
sudo journalctl -u polstation-camera-preview -n 100 --no-pager
sudo journalctl -u polstation-sensor-preview -n 100 --no-pager
sudo journalctl -u polstation-acquisition -n 100 --no-pager
sudo journalctl -u polstation-dashboard -n 100 --no-pager
```

`polstation-preview.target` starts and stops the three diagnostic processes as a
group. They remain separate services: a crashed process restarts after 10 seconds
without taking down the other two. The camera and sensor producers publish bounded
latest-value files under `/var/lib/polstation/state`; the dashboard only reads
them. Stop the entire diagnostic stack cleanly with:

```sh
sudo systemctl stop polstation-preview.target
```

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
