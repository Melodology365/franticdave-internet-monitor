#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/franticdave/internet-monitor"
SERVICE_NAME="internet-monitor.service"

mkdir -p "$APP_DIR"
cp internet_monitor.py "$APP_DIR/"

if [ ! -f "$APP_DIR/config.json" ]; then
  cp config.example.json "$APP_DIR/config.json"
fi

sudo cp "$SERVICE_NAME" /etc/systemd/system/"$SERVICE_NAME"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "Installed and started FranticDave Internet Monitor"
sudo systemctl --no-pager --full status "$SERVICE_NAME" || true
