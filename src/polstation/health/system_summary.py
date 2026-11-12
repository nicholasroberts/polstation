"""Publish bounded boot, uptime and storage status for the read-only dashboard."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import signal
import threading

from polstation.config import load_config
from polstation.logging.setup import configure
from polstation.storage.layout import prepare_state
from polstation.storage.manifests import write_json


MAX_RECENT_BOOTS = 32


def _uptime_seconds():
    return float(Path("/proc/uptime").read_text().split()[0])


def _boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def system_summary(config, *, now=None, uptime=None, boot_id=None, previous=None):
    now = now or datetime.now(timezone.utc)
    uptime = _uptime_seconds() if uptime is None else uptime
    boot_id = _boot_id() if boot_id is None else boot_id
    previous = previous if isinstance(previous, dict) else {}
    boots = list(previous.get("recent_boots", []))
    new_boot = previous.get("boot_id") != boot_id
    if not boots or boots[-1].get("boot_id") != boot_id:
        boots.append({
            "boot_id": boot_id,
            "observed_at_utc": now.isoformat(),
            "estimated_boot_at_utc": (now - timedelta(seconds=uptime)).isoformat(),
        })
    storage = shutil.disk_usage(config["storage"]["data_root"])
    return {
        "schema_version": 1,
        "mode": "system-summary",
        "updated_at_utc": now.isoformat(),
        "boot_id": boot_id,
        "uptime_seconds": uptime,
        "estimated_boot_at_utc": (now - timedelta(seconds=uptime)).isoformat(),
        "observed_boot_count": int(previous.get("observed_boot_count", 0)) + int(new_boot),
        "recent_boots": boots[-MAX_RECENT_BOOTS:],
        "storage": {
            "path": str(config["storage"]["data_root"]),
            "total_bytes": storage.total,
            "used_bytes": storage.used,
            "free_bytes": storage.free,
            "minimum_free_bytes": config["storage"]["minimum_free_bytes"],
        },
        "provenance": config["provenance"],
    }


def publish(config, *, now=None, uptime=None, boot_id=None):
    prepare_state(config)
    path = Path(config["storage"]["state_root"]) / "system-summary.json"
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        previous = {}
    value = system_summary(
        config, now=now, uptime=uptime, boot_id=boot_id, previous=previous
    )
    write_json(path, value, replace=True)
    return value


def run(config, stop, *, interval=30):
    while not stop.is_set():
        started = datetime.now(timezone.utc)
        publish(config, now=started)
        stop.wait(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    configure()
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    run(load_config(args.config), stop, interval=args.interval)


if __name__ == "__main__":
    main()
