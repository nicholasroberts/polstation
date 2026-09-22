"""Health describes scaffold liveness, never camera readiness."""
import json
from datetime import datetime, timezone
from pathlib import Path
from polstation import __version__
from polstation.storage.manifests import config_digest, write_json


def publish(config, state, available_bytes=None):
    value = {"schema_version": 1, "updated_at_utc": datetime.now(timezone.utc).isoformat(),
             "state": state, "mode": "scaffold", "hardware_ready": False,
             "software_version": __version__, "free_bytes": available_bytes,
             "config_sha256": config_digest(config), **config["provenance"]}
    write_json(Path(config["storage"]["state_root"]) / "health.json", value, replace=True)


def read(config):
    try:
        value = json.loads((Path(config["storage"]["state_root"]) / "health.json").read_text())
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(value["updated_at_utc"])).total_seconds()
        value["stale"] = age < 0 or age > config["dashboard"]["stale_after_seconds"]
        return value
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"state": "unavailable", "stale": True, "hardware_ready": False}
