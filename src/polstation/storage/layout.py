"""Separate immutable scientific data from replaceable runtime status."""
from pathlib import Path
import shutil


def prepare(config):
    for key in ("data_root", "state_root"):
        Path(config["storage"][key]).mkdir(parents=True, exist_ok=True)


def free_bytes(config):
    return shutil.disk_usage(config["storage"]["data_root"]).free
