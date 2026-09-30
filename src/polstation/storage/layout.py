"""Separate immutable scientific data from replaceable runtime status."""
from pathlib import Path
import shutil


def prepare(config):
    for key in ("data_root", "state_root"):
        Path(config["storage"][key]).mkdir(parents=True, exist_ok=True)


def prepare_state(config):
    """Create only replaceable runtime state storage for diagnostic producers."""
    Path(config["storage"]["state_root"]).mkdir(parents=True, exist_ok=True)


def free_bytes(config):
    return shutil.disk_usage(config["storage"]["data_root"]).free
