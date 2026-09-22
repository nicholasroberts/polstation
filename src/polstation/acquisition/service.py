"""Headless lifecycle scaffold. Does not acquire images or read sensors."""
import argparse
import logging
import signal
import threading
from polstation.config import load_config
from polstation.health.status import publish
from polstation.logging.setup import configure
from polstation.storage.layout import free_bytes, prepare

logger = logging.getLogger(__name__)


def run(config, stop, *, once=False):
    retry = config["acquisition"]["retry_initial_seconds"]
    while not stop.is_set():
        try:
            prepare(config)
            available = free_bytes(config)
            state = "low_disk" if available < config["storage"]["minimum_free_bytes"] else "scaffold_idle"
            publish(config, state, available)
            if state == "low_disk":
                logger.warning("Low disk space; existing data retained")
            if once:
                return
            retry = config["acquisition"]["retry_initial_seconds"]
            stop.wait(config["acquisition"]["heartbeat_seconds"])
        except OSError:
            logger.exception("Storage/status failure; retrying in %s seconds", retry)
            if once:
                raise
            stop.wait(retry)
            retry = min(retry * 2, config["acquisition"]["retry_max_seconds"])
    try:
        publish(config, "stopped")
    except OSError:
        logger.exception("Could not publish shutdown status")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true", help="Publish one scaffold heartbeat and exit")
    args = parser.parse_args()
    configure()
    config = load_config(args.config)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    logger.info("Starting scaffold mode; hardware acquisition is not implemented")
    run(config, stop, once=args.once)
