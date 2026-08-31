#!/usr/bin/env python3

import csv
import json
import socket
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
LOG_FILE = BASE_DIR / "outages.csv"

DEFAULT_CONFIG = {
    "check_interval_seconds": 5,
    "outage_threshold_seconds": 30,
    "connect_timeout_seconds": 3,
    "targets": [
        {"host": "1.1.1.1", "port": 443},
        {"host": "8.8.8.8", "port": 53},
        {"host": "9.9.9.9", "port": 53}
    ]
}


def now():
    return datetime.now().astimezone()


def load_config():
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as file:
            config = json.load(file)
        merged = DEFAULT_CONFIG.copy()
        merged.update(config)
        return merged
    except Exception as exc:
        print(f"{now().isoformat()} Config error, using defaults: {exc}", flush=True)
        return DEFAULT_CONFIG.copy()


def internet_is_up(config):
    targets = config.get("targets", DEFAULT_CONFIG["targets"])
    timeout = float(config.get("connect_timeout_seconds", 3))

    for target in targets:
        try:
            with socket.create_connection(
                (target["host"], int(target["port"])),
                timeout=timeout
            ):
                return True
        except OSError:
            pass

    return False


def ensure_log():
    if LOG_FILE.exists():
        return

    with LOG_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "outage_started",
            "outage_ended",
            "duration_seconds",
            "duration_minutes"
        ])


def log_outage(started, ended):
    duration = (ended - started).total_seconds()

    with LOG_FILE.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            started.isoformat(timespec="seconds"),
            ended.isoformat(timespec="seconds"),
            round(duration, 1),
            round(duration / 60, 2)
        ])


def main():
    ensure_log()
    print(f"{now().isoformat()} FranticDave Internet Monitor started", flush=True)

    failure_started = None
    outage_declared = False

    while True:
        config = load_config()
        interval = max(1, float(config.get("check_interval_seconds", 5)))
        threshold = max(1, float(config.get("outage_threshold_seconds", 30)))
        current = now()
        online = internet_is_up(config)

        if online:
            if outage_declared and failure_started is not None:
                log_outage(failure_started, current)
                duration = (current - failure_started).total_seconds()
                print(
                    f"{current.isoformat()} INTERNET RESTORED after {duration:.1f} seconds",
                    flush=True
                )

            failure_started = None
            outage_declared = False

        else:
            if failure_started is None:
                failure_started = current
                print(f"{current.isoformat()} Connectivity check failed", flush=True)

            elapsed = (current - failure_started).total_seconds()

            if not outage_declared and elapsed >= threshold:
                outage_declared = True
                print(
                    f"{current.isoformat()} INTERNET OUTAGE DECLARED "
                    f"(down for {elapsed:.1f} seconds)",
                    flush=True
                )

        time.sleep(interval)


if __name__ == "__main__":
    main()
