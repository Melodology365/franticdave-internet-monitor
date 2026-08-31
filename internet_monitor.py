#!/usr/bin/env python3

import csv
import json
import smtplib
import socket
import time
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
REMOTE_CACHE_FILE = BASE_DIR / "remote_config_cache.json"
SECRETS_FILE = BASE_DIR / "secrets.json"
LOG_FILE = BASE_DIR / "outages.csv"
ACTIVE_OUTAGE_FILE = BASE_DIR / "active_outage.json"

DEFAULT_CONFIG = {
    "site_name": "Ashton Test Monitor",
    "check_interval_seconds": 5,
    "log_after_seconds": 10,
    "email_after_seconds": 60,
    "config_refresh_seconds": 60,
    "connect_timeout_seconds": 3,
    "email_enabled": True,
    "recovery_email_enabled": True,
    "email_to": "david@cabmaster.com",
    "email_from": "farjeoncourt@gmail.com",
    "remote_config_url": "",
    "targets": [
        {"host": "1.1.1.1", "port": 443},
        {"host": "8.8.8.8", "port": 53},
        {"host": "9.9.9.9", "port": 53}
    ]
}


def now():
    return datetime.now().astimezone()


def merge_config(config):
    merged = DEFAULT_CONFIG.copy()
    merged.update(config or {})
    return merged


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def load_local_config():
    try:
        return merge_config(load_json(CONFIG_FILE))
    except Exception as exc:
        print(f"{now().isoformat()} Local config error, using defaults: {exc}", flush=True)
        return DEFAULT_CONFIG.copy()


def load_cached_remote_config():
    try:
        return load_json(REMOTE_CACHE_FILE)
    except Exception:
        return None


def fetch_remote_config(url, timeout=10):
    request = urllib.request.Request(url, headers={"User-Agent": "FranticDaveInternetMonitor/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    remote = json.loads(raw)
    if not isinstance(remote, dict):
        raise ValueError("Remote config must be a JSON object")
    return remote


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
            "site_name",
            "outage_started",
            "outage_ended",
            "duration_seconds",
            "duration_minutes",
            "email_required",
            "email_sent"
        ])


def log_outage(site_name, started, ended, email_required, email_sent):
    duration = (ended - started).total_seconds()

    with LOG_FILE.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            site_name,
            started.isoformat(timespec="seconds"),
            ended.isoformat(timespec="seconds"),
            round(duration, 1),
            round(duration / 60, 2),
            "yes" if email_required else "no",
            "yes" if email_sent else "no"
        ])


def load_secrets():
    try:
        data = load_json(SECRETS_FILE)
        password = str(data.get("gmail_app_password", "")).replace(" ", "")
        if not password:
            raise ValueError("gmail_app_password is empty")
        return password
    except Exception as exc:
        raise RuntimeError(f"Email secrets unavailable: {exc}") from exc


def send_recovery_email(config, started, ended):
    duration = (ended - started).total_seconds()
    site_name = config.get("site_name", "Internet Monitor")
    email_from = config.get("email_from", DEFAULT_CONFIG["email_from"])
    email_to = config.get("email_to", DEFAULT_CONFIG["email_to"])

    message = EmailMessage()
    message["From"] = email_from
    message["To"] = email_to
    message["Subject"] = f"Internet outage: {site_name}"
    message.set_content(
        f"Internet connectivity was lost at {site_name}.\n\n"
        f"Outage started: {started.isoformat(timespec='seconds')}\n"
        f"Internet restored: {ended.isoformat(timespec='seconds')}\n"
        f"Duration: {duration:.1f} seconds ({duration / 60:.2f} minutes)\n"
    )

    app_password = load_secrets()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
        smtp.login(email_from, app_password)
        smtp.send_message(message)


def save_active_outage(started, log_threshold_reached):
    save_json(ACTIVE_OUTAGE_FILE, {
        "started": started.isoformat(),
        "log_threshold_reached": bool(log_threshold_reached)
    })


def clear_active_outage():
    try:
        ACTIVE_OUTAGE_FILE.unlink()
    except FileNotFoundError:
        pass


def main():
    ensure_log()
    print(f"{now().isoformat()} FranticDave Internet Monitor started", flush=True)

    local_config = load_local_config()
    cached_remote = load_cached_remote_config()
    config = merge_config({**local_config, **(cached_remote or {})})
    last_remote_refresh = 0.0

    failure_started = None
    log_threshold_reached = False
    outage_declared = False

    while True:
        local_config = load_local_config()
        refresh_seconds = max(10, float(local_config.get("config_refresh_seconds", 60)))
        current_monotonic = time.monotonic()

        if current_monotonic - last_remote_refresh >= refresh_seconds:
            last_remote_refresh = current_monotonic
            remote_url = str(local_config.get("remote_config_url", "")).strip()
            if remote_url:
                try:
                    remote = fetch_remote_config(remote_url)
                    save_json(REMOTE_CACHE_FILE, remote)
                    cached_remote = remote
                    print(f"{now().isoformat()} Remote config refreshed", flush=True)
                except Exception as exc:
                    print(f"{now().isoformat()} Remote config refresh failed, keeping last good config: {exc}", flush=True)

        config = merge_config({**local_config, **(cached_remote or {})})
        interval = max(1, float(config.get("check_interval_seconds", 5)))
        log_after = max(1, float(config.get("log_after_seconds", 10)))
        email_after = max(log_after, float(config.get("email_after_seconds", 60)))
        current = now()
        online = internet_is_up(config)

        if online:
            if failure_started is not None:
                duration = (current - failure_started).total_seconds()

                if log_threshold_reached or duration >= log_after:
                    email_required = (
                        bool(config.get("email_enabled", True))
                        and bool(config.get("recovery_email_enabled", True))
                        and duration >= email_after
                    )
                    email_sent = False

                    if email_required:
                        try:
                            send_recovery_email(config, failure_started, current)
                            email_sent = True
                            print(f"{current.isoformat()} Recovery email sent to {config.get('email_to')}", flush=True)
                        except Exception as exc:
                            print(f"{current.isoformat()} Recovery email failed: {exc}", flush=True)

                    log_outage(
                        config.get("site_name", "Internet Monitor"),
                        failure_started,
                        current,
                        email_required,
                        email_sent
                    )
                    print(
                        f"{current.isoformat()} INTERNET RESTORED after {duration:.1f} seconds",
                        flush=True
                    )

            failure_started = None
            log_threshold_reached = False
            outage_declared = False
            clear_active_outage()

        else:
            if failure_started is None:
                failure_started = current
                print(f"{current.isoformat()} Connectivity check failed", flush=True)

            elapsed = (current - failure_started).total_seconds()

            if not log_threshold_reached and elapsed >= log_after:
                log_threshold_reached = True
                save_active_outage(failure_started, True)
                print(
                    f"{current.isoformat()} OUTAGE LOG THRESHOLD REACHED "
                    f"(down for {elapsed:.1f} seconds)",
                    flush=True
                )

            if not outage_declared and elapsed >= email_after:
                outage_declared = True
                print(
                    f"{current.isoformat()} EMAIL THRESHOLD REACHED "
                    f"(down for {elapsed:.1f} seconds; email will be sent on recovery)",
                    flush=True
                )

        time.sleep(interval)


if __name__ == "__main__":
    main()
