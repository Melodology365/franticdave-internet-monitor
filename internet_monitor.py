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
STATUS_LOG_FILE = BASE_DIR / "status.csv"
ACTIVE_OUTAGE_FILE = BASE_DIR / "active_outage.json"

DEFAULT_CONFIG = {
    "site_name": "Ashton Test Monitor",
    "check_interval_seconds": 5,
    "log_after_seconds": 10,
    "email_after_seconds": 60,
    "config_refresh_seconds": 60,
    "status_interval_seconds": 60,
    "status_log_enabled": True,
    "status_log_interval_hours": 24,
    "connect_timeout_seconds": 3,
    "email_enabled": True,
    "recovery_email_enabled": True,
    "email_to": "david@cabmaster.com",
    "email_from": "farjeoncourt@gmail.com",
    "remote_config_url": "",
    "remote_log_url": "",
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


def get_remote_endpoint(config):
    endpoint = str(config.get("remote_log_url", "")).strip()
    if not endpoint:
        endpoint = str(config.get("remote_config_url", "")).strip()
    return endpoint


def post_json(config, payload):
    endpoint = get_remote_endpoint(config)
    if not endpoint:
        return False

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "FranticDaveInternetMonitor/1.0"
        },
        method="POST"
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read().decode("utf-8")
    result = json.loads(raw)
    if not isinstance(result, dict) or not result.get("success"):
        raise RuntimeError(f"Remote log rejected entry: {raw}")
    return True


def post_remote_outage(config, started, ended, email_required, email_sent):
    duration = (ended - started).total_seconds()
    payload = {
        "log_type": "outage",
        "site_name": config.get("site_name", "Internet Monitor"),
        "outage_started": started.isoformat(timespec="seconds"),
        "outage_ended": ended.isoformat(timespec="seconds"),
        "duration_seconds": round(duration, 1),
        "duration_minutes": round(duration / 60, 2),
        "email_required": "yes" if email_required else "no",
        "email_sent": "yes" if email_sent else "no"
    }
    return post_json(config, payload)


def post_remote_status(config, record):
    payload = {"log_type": "status", **record}
    return post_json(config, payload)


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


def ensure_status_log():
    if STATUS_LOG_FILE.exists():
        return

    with STATUS_LOG_FILE.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "site_name",
            "entry_type",
            "timestamp",
            "monitor_started",
            "monitor_uptime_hours",
            "total_checks",
            "failed_checks",
            "total_outages",
            "session_outages",
            "last_outage_started",
            "last_outage_duration_seconds",
            "current_status"
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


def read_outage_history():
    total = 0
    last_started = ""
    last_duration = ""

    try:
        with LOG_FILE.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if not row.get("outage_started"):
                    continue
                total += 1
                last_started = row.get("outage_started", "")
                last_duration = row.get("duration_seconds", "")
    except Exception as exc:
        print(f"{now().isoformat()} Could not read outage history: {exc}", flush=True)

    return total, last_started, last_duration


def make_status_record(config, entry_type, timestamp, monitor_started, total_checks,
                       failed_checks, total_outages, session_outages,
                       last_outage_started, last_outage_duration, current_status):
    uptime_hours = max(0.0, (timestamp - monitor_started).total_seconds() / 3600)
    return {
        "site_name": config.get("site_name", "Internet Monitor"),
        "entry_type": entry_type,
        "timestamp": timestamp.isoformat(timespec="seconds"),
        "monitor_started": monitor_started.isoformat(timespec="seconds"),
        "monitor_uptime_hours": round(uptime_hours, 2),
        "total_checks": total_checks,
        "failed_checks": failed_checks,
        "total_outages": total_outages,
        "session_outages": session_outages,
        "last_outage_started": last_outage_started,
        "last_outage_duration_seconds": last_outage_duration,
        "current_status": current_status
    }


def append_local_status(record):
    with STATUS_LOG_FILE.open("a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            record["site_name"],
            record["entry_type"],
            record["timestamp"],
            record["monitor_started"],
            record["monitor_uptime_hours"],
            record["total_checks"],
            record["failed_checks"],
            record["total_outages"],
            record["session_outages"],
            record["last_outage_started"],
            record["last_outage_duration_seconds"],
            record["current_status"]
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


def print_config_summary(config, cached_remote):
    remote_url = str(config.get("remote_config_url", "")).strip()
    print(f"{now().isoformat()} Site: {config.get('site_name')}", flush=True)
    print(
        f"{now().isoformat()} Monitoring every {config.get('check_interval_seconds')}s | "
        f"log after {config.get('log_after_seconds')}s | "
        f"email after {config.get('email_after_seconds')}s",
        flush=True
    )
    print(
        f"{now().isoformat()} Email: {config.get('email_from')} -> {config.get('email_to')} | "
        f"enabled={bool(config.get('email_enabled', True))}",
        flush=True
    )
    if remote_url:
        source = "cached remote config available" if cached_remote else "no cached remote config yet"
        print(
            f"{now().isoformat()} Remote config enabled | refresh every "
            f"{config.get('config_refresh_seconds')}s | {source}",
            flush=True
        )
        print(f"{now().isoformat()} Remote outage logging enabled", flush=True)
    else:
        print(
            f"{now().isoformat()} Remote config NOT CONFIGURED. "
            f"Set remote_config_url in config.json when the Google Drive config URL is ready.",
            flush=True
        )
    print(
        f"{now().isoformat()} Console heartbeat every {config.get('status_interval_seconds', 60)}s | "
        f"audit log every {config.get('status_log_interval_hours', 24)}h | "
        f"enabled={bool(config.get('status_log_enabled', True))}",
        flush=True
    )


def main():
    ensure_log()
    ensure_status_log()
    monitor_started = now()
    print(f"{monitor_started.isoformat()} FranticDave Internet Monitor started", flush=True)

    local_config = load_local_config()
    cached_remote = load_cached_remote_config()
    config = merge_config({**local_config, **(cached_remote or {})})
    print_config_summary(config, cached_remote)

    total_outages, last_outage_started, last_outage_duration = read_outage_history()
    total_checks = 0
    failed_checks = 0
    session_outages = 0

    startup_record = make_status_record(
        config, "STARTED", monitor_started, monitor_started,
        total_checks, failed_checks, total_outages, session_outages,
        last_outage_started, last_outage_duration, "STARTING"
    )
    append_local_status(startup_record)
    print(f"{now().isoformat()} STARTED entry written to local audit log", flush=True)

    startup_remote_pending = bool(config.get("status_log_enabled", True))
    last_startup_upload_attempt = 0.0
    last_remote_refresh = 0.0
    last_status = 0.0
    last_status_log = time.monotonic()

    failure_started = None
    log_threshold_reached = False
    outage_declared = False

    while True:
        local_config = load_local_config()
        current_monotonic = time.monotonic()
        config = merge_config({**local_config, **(cached_remote or {})})
        refresh_seconds = max(10, float(config.get("config_refresh_seconds", 60)))

        if current_monotonic - last_remote_refresh >= refresh_seconds:
            last_remote_refresh = current_monotonic
            remote_url = str(local_config.get("remote_config_url", "")).strip()
            if remote_url:
                try:
                    remote = fetch_remote_config(remote_url)
                    save_json(REMOTE_CACHE_FILE, remote)
                    cached_remote = remote
                    print(f"{now().isoformat()} Remote config refreshed successfully", flush=True)
                except Exception as exc:
                    print(f"{now().isoformat()} Remote config refresh failed, keeping last good config: {exc}", flush=True)

        config = merge_config({**local_config, **(cached_remote or {})})
        interval = max(1, float(config.get("check_interval_seconds", 5)))
        log_after = max(1, float(config.get("log_after_seconds", 10)))
        email_after = max(1, float(config.get("email_after_seconds", 60)))
        status_interval = max(10, float(config.get("status_interval_seconds", 60)))
        status_log_hours = max(0.01, float(config.get("status_log_interval_hours", 24)))
        status_log_seconds = status_log_hours * 3600
        status_log_enabled = bool(config.get("status_log_enabled", True))
        current = now()
        online = internet_is_up(config)
        total_checks += 1

        if not online:
            failed_checks += 1

        if online:
            if startup_remote_pending and status_log_enabled and current_monotonic - last_startup_upload_attempt >= 60:
                last_startup_upload_attempt = current_monotonic
                try:
                    startup_record["current_status"] = "ONLINE"
                    if post_remote_status(config, startup_record):
                        startup_remote_pending = False
                        print(f"{current.isoformat()} STARTED entry uploaded to Google Drive status log", flush=True)
                except Exception as exc:
                    print(f"{current.isoformat()} Remote STARTED status upload failed: {exc}", flush=True)

            if current_monotonic - last_status >= status_interval:
                last_status = current_monotonic
                print(
                    f"{current.isoformat()} STATUS OK | internet online | "
                    f"site={config.get('site_name')} | checks={total_checks} | "
                    f"confirmed outages this session={session_outages} | next check in {interval:g}s",
                    flush=True
                )

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

                    total_outages += 1
                    session_outages += 1
                    last_outage_started = failure_started.isoformat(timespec="seconds")
                    last_outage_duration = round(duration, 1)

                    try:
                        if post_remote_outage(config, failure_started, current, email_required, email_sent):
                            print(f"{current.isoformat()} Outage uploaded to Google Drive log", flush=True)
                    except Exception as exc:
                        print(f"{current.isoformat()} Remote outage log upload failed: {exc}", flush=True)

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

        if status_log_enabled and current_monotonic - last_status_log >= status_log_seconds:
            last_status_log = current_monotonic
            current_status = "ONLINE" if online else "OFFLINE"
            record = make_status_record(
                config, "STATUS", current, monitor_started,
                total_checks, failed_checks, total_outages, session_outages,
                last_outage_started, last_outage_duration, current_status
            )
            append_local_status(record)
            print(
                f"{current.isoformat()} STATUS entry written to local audit log | "
                f"checks={total_checks} | failed checks={failed_checks} | total outages={total_outages}",
                flush=True
            )

            if online:
                try:
                    if post_remote_status(config, record):
                        print(f"{current.isoformat()} STATUS entry uploaded to Google Drive status log", flush=True)
                except Exception as exc:
                    print(f"{current.isoformat()} Remote STATUS upload failed: {exc}", flush=True)

        time.sleep(interval)


if __name__ == "__main__":
    main()
